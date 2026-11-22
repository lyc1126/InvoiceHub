<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import { costBase, type CostSnapshot } from "../api/costV2";
import type { Company } from "../api/types";
import { errorText, money } from "../format";
import { toast } from "../toast";
import { companySourceKey } from "../stores/companies";
import WsModal from "./WsModal.vue";

interface OpeningRow { account_code: string; unit: string; quantity: string; amount: string }
interface Setup { mappings: Record<string, string>; opening: { month: string; items: OpeningRow[] } | null; covered_months: string[]; source: string }
interface Payload { revision: string; config_revision: number; binding_state: "current" | "needs_review"; setup: Setup; accounts: { code: string; name: string }[]; book_error: string }
interface Preview { revision: string; preview_hash: string; before: Setup; after: Setup }

const props = defineProps<{ company: Company; snapshot: CostSnapshot | null; saved: number }>();
const emit = defineEmits<{ changed: [] }>();
const data = ref<Payload | null>(null);
const mappings = ref<Record<string, string>>({});
const openingOn = ref(false);
const openingMonth = ref("");
const opening = ref<OpeningRow[]>([]);
const covered = ref<string[]>([]);
const newMonth = ref("");
const source = ref("");
const preview = ref<{ body: Record<string, unknown>; result: Preview } | null>(null);
const confirming = ref(false);
const loading = ref(false);
const saving = ref(false);
const unknown = ref(false);
const edited = ref(false), stale = ref(false);
const error = ref("");
const base = computed(() => `${costBase(props.company.id)}/inventory-setup`);
// Standard item names from the V2 snapshot, plus any saved names (aliases expanded by the
// backend) so a confirmed mapping is never hidden just because the catalog changed.
const names = computed(() => [...new Set([...(props.snapshot?.items ?? []).map(item => item.name), ...Object.keys(mappings.value)])].sort());
const accountName = computed(() => new Map((data.value?.accounts ?? []).map(account => [account.code, account.name])));
const reconciliation = computed(() => props.snapshot?.book_reconciliation);
const RECON_STATES: Record<string, string> = { matched: "一致", different: "有差额", needs_review: "待核对", unassigned: "账面科目未对照" };
let generation = 0;
let previewEpoch = 0;

function reset(payload: Payload): void {
  mappings.value = { ...payload.setup.mappings };
  openingOn.value = payload.setup.opening !== null;
  openingMonth.value = payload.setup.opening?.month ?? "";
  opening.value = payload.setup.opening?.items.map(row => ({ ...row })) ?? [];
  covered.value = [...payload.setup.covered_months];
  source.value = payload.setup.source;
  preview.value = null;
}
function touch(): void { previewEpoch += 1; preview.value = null; edited.value = true; }
// Unmapped names hold "" so the select shows its 未对照 option; build() drops empty values.
watch(names, list => { for (const name of list) if (!(name in mappings.value)) mappings.value[name] = ""; }, { immediate: true });
function addMonth(): void { if (/^\d{4}-\d{2}$/.test(newMonth.value) && !covered.value.includes(newMonth.value)) { covered.value = [...covered.value, newMonth.value].sort(); touch(); } newMonth.value = ""; }

async function load(): Promise<void> {
  const mine = ++generation;
  loading.value = true;
  try {
    const result = await request<Payload>(base.value, { timeoutMs: 120_000 });
    if (mine !== generation) return;
    data.value = result;
    reset(result);
    edited.value = false; stale.value = false; previewEpoch += 1;
    unknown.value = false;
    error.value = "";
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) { loading.value = false; saving.value = false; } }
}

function build(): Setup | string {
  const setup: Setup = { mappings: Object.fromEntries(Object.entries(mappings.value).filter(([, code]) => code)), opening: null, covered_months: covered.value, source: source.value.trim() };
  if (openingOn.value) {
    if (!/^\d{4}-\d{2}$/.test(openingMonth.value)) return "请选择库存期初月份。";
    for (const [index, row] of opening.value.entries()) {
      if (!row.account_code || !row.unit.trim()) return `期初第 ${index + 1} 行须选择科目并填写单位。`;
      if (!/^-?(0|[1-9]\d{0,14})(\.\d{1,8})?$/.test(row.quantity.trim()) || !/^-?(0|[1-9]\d{0,14})(\.\d{1,2})?$/.test(row.amount.trim())) return `期初第 ${index + 1} 行数量或金额无效（金额最多两位小数）。`;
    }
    // An explicit empty opening is a confirmed zero baseline, unlike an absent one.
    setup.opening = { month: openingMonth.value, items: opening.value.map(row => ({ account_code: row.account_code, unit: row.unit.trim(), quantity: row.quantity.trim(), amount: row.amount.trim() })) };
  }
  if ((Object.keys(setup.mappings).length || setup.opening) && !setup.source) return "请填写对照与期初的来源说明（如 2026-06 账套余额表）。";
  return setup;
}

async function runPreview(): Promise<void> {
  if (!data.value || unknown.value || stale.value) return;
  const mine = generation, epoch = ++previewEpoch;
  const setup = build();
  if (typeof setup === "string") { error.value = setup; return; }
  const body = { revision: data.value.revision, setup };
  saving.value = true;
  error.value = "";
  try {
    const result = await request<Preview>(`${base.value}/preview`, { method: "POST", body, timeoutMs: 120_000 });
    if (mine === generation && epoch === previewEpoch) preview.value = { body, result };
  } catch (cause) {
    if (mine !== generation || epoch !== previewEpoch) return;
    if (cause instanceof ApiError && cause.status === 409) await load();
    error.value = errorText(cause);
  } finally { if (mine === generation) saving.value = false; }
}

async function save(): Promise<void> {
  const current = preview.value;
  if (!current || saving.value || unknown.value || stale.value) return;
  const mine = generation;
  saving.value = true;
  try {
    const result = await request<{ changed: boolean }>(base.value, { method: "PUT", body: { ...current.body, preview_hash: current.result.preview_hash, confirm: true }, timeoutMs: 120_000 });
    if (mine !== generation) return;
    confirming.value = false;
    toast(result.changed ? "库存科目对照已保存；成本、进销存比较与凭证草稿将使用新对照。" : "对照没有变化，未写入。");
    emit("changed");
    await load();
  } catch (cause) {
    if (mine !== generation) return;
    confirming.value = false;
    preview.value = null;
    if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
      if (cause.status === 409) await load();
      error.value = errorText(cause);
    } else {
      unknown.value = true;
      error.value = "库存对照保存结果待核对，请读取保存结果；不会自动重发。";
    }
  } finally { if (mine === generation) saving.value = false; }
}

watch(() => props.saved, () => {
  previewEpoch += 1; preview.value = null; confirming.value = false;
  if (saving.value) { if (edited.value) stale.value = true; return; }
  if (edited.value && !unknown.value) stale.value = true; else void load();
});
watch(() => companySourceKey(props.company, ["cost_invoice_dir", "issued_invoice_dir"]), () => {
  generation += 1; previewEpoch += 1; data.value = null; preview.value = null; confirming.value = false;
  saving.value = false; unknown.value = false; stale.value = false; edited.value = false; error.value = ""; void load();
}, { immediate: true });
onBeforeUnmount(() => { generation += 1; previewEpoch += 1; });
</script>

<template>
  <section class="cost-inventory" aria-label="库存对照">
    <p class="overview-notice">只选择账套已启用的末级库存科目，不新建科目。对照、期初与完整读回月份确认后写入公司根目录「库存科目对照.json」，V2 成本、进销存比较与凭证草稿共用；已确认期初不会被历史发票自动纠正。</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }} <button v-if="unknown" type="button" :disabled="loading" @click="load">读取保存结果</button></p>
    <p v-if="stale" class="banner banner--note">来源已更新，库存对照草稿保留，旧预览已作废。<button type="button" :disabled="loading" @click="load">放弃草稿并重新读取</button></p>
    <template v-if="data">
      <p v-if="data.book_error" class="banner banner--note">{{ data.book_error }}</p>
      <p v-if="data.binding_state === 'needs_review' && data.config_revision" class="banner banner--note" role="status">账套科目表已变化，原对照需重新核对并确认后才会生效。</p>
      <p v-if="!data.accounts.length" class="muted">账套读回中没有可选的“库存商品”末级科目；请先在做账中读回科目表。</p>
      <div class="overview-table-wrap"><table class="grid" aria-label="品目库存科目对照">
        <thead><tr><th>品名</th><th>库存科目</th></tr></thead>
        <tbody><tr v-for="name in names" :key="name">
          <td>{{ name }}</td>
          <td><select v-model="mappings[name]" :aria-label="`库存科目 ${name}`" :disabled="saving || unknown" @change="touch"><option value="">未对照（按品类关键字建议）</option><option v-for="account in data.accounts" :key="account.code" :value="account.code">{{ account.code }} {{ account.name }}</option></select></td>
        </tr></tbody>
      </table></div>
      <fieldset class="cost-inventory__group">
        <legend><label><input v-model="openingOn" type="checkbox" :disabled="saving || unknown" @change="touch"> 设置库存期初（按科目）</label></legend>
        <template v-if="openingOn">
          <label class="field">期初月份<input v-model="openingMonth" type="month" aria-label="期初月份" @input="touch"></label>
          <div v-for="(row, index) in opening" :key="index" class="toolbar">
            <select v-model="row.account_code" :aria-label="`期初科目 ${index + 1}`" @change="touch"><option value="">选择科目</option><option v-for="account in data.accounts" :key="account.code" :value="account.code">{{ account.code }} {{ account.name }}</option></select>
            <input v-model="row.unit" :aria-label="`期初单位 ${index + 1}`" placeholder="单位" size="4" @input="touch">
            <input v-model="row.quantity" :aria-label="`期初数量 ${index + 1}`" placeholder="数量" inputmode="decimal" size="10" @input="touch">
            <input v-model="row.amount" :aria-label="`期初金额 ${index + 1}`" placeholder="金额" inputmode="decimal" size="12" @input="touch">
            <button type="button" class="ghost" @click="opening.splice(index, 1); touch()">删除</button>
          </div>
          <button type="button" @click="opening.push({ account_code: '', unit: '', quantity: '0', amount: '0.00' }); touch()">添加期初行</button>
          <p class="muted">没有期初行表示明确的零期初。</p>
        </template>
      </fieldset>
      <fieldset class="cost-inventory__group">
        <legend>已完整读回的月份</legend>
        <p class="muted">只有声明完整且实际读回的月份才参与账面核对；不按文件名或最后读回月份推断。</p>
        <span v-for="month in covered" :key="month" class="tag">{{ month }} <button type="button" class="ghost" :aria-label="`移除 ${month}`" @click="covered = covered.filter(item => item !== month); touch()">×</button></span>
        <div class="toolbar"><input v-model="newMonth" type="month" aria-label="添加读回月份"><button type="button" @click="addMonth">添加</button></div>
      </fieldset>
      <label class="field">来源说明<input v-model="source" aria-label="对照来源说明" maxlength="200" placeholder="如 2026-06 账套科目余额表" @input="touch"></label>
      <div class="actions">
        <button type="button" class="primary" :disabled="saving || unknown || stale" :aria-busy="saving" @click="runPreview">预览</button>
        <button type="button" :disabled="!preview || saving || unknown || stale" @click="confirming = true">确认保存…</button>
      </div>
      <p v-if="preview" class="muted">预览：对照 {{ Object.keys(preview.result.before.mappings).length }} → {{ Object.keys(preview.result.after.mappings).length }} 项（含自动展开的品目别名）；期初 {{ preview.result.after.opening ? `${preview.result.after.opening.month}，${preview.result.after.opening.items.length} 个科目` : "未设置" }}；读回月份 {{ preview.result.after.covered_months.length }} 个。</p>
    </template>
    <p v-else-if="loading" class="muted">读取中…</p>
    <section v-if="reconciliation" aria-label="账面库存核对">
      <h4>账面库存核对（{{ RECON_STATES[reconciliation.state] ?? reconciliation.state }}）</h4>
      <p class="muted">{{ reconciliation.message }}<template v-if="reconciliation.missing_months.length"> 缺少读回月份：{{ reconciliation.missing_months.join("、") }}</template></p>
      <div v-if="reconciliation.items.length" class="overview-table-wrap"><table class="grid">
        <thead><tr><th>科目</th><th>品类</th><th>单位</th><th class="num">发票滚动数量</th><th class="num">发票滚动金额</th><th class="num">账面数量</th><th class="num">账面金额</th><th class="num">数量差</th><th class="num">金额差</th><th>状态</th></tr></thead>
        <tbody><tr v-for="(row, index) in reconciliation.items" :key="index" :class="{ 'check--failed': row.state !== 'matched' }">
          <td>{{ row.account_code ? `${row.account_code} ${accountName.get(row.account_code) ?? ""}` : "未对照" }}</td><td>{{ row.name }}</td><td>{{ row.unit }}</td>
          <td class="num">{{ row.expected_quantity ?? "—" }}</td><td class="num">{{ money(row.expected_amount ?? null) }}</td>
          <td class="num">{{ row.book_quantity ?? "待核对" }}</td><td class="num">{{ row.book_amount === null ? "待核对" : money(row.book_amount) }}</td>
          <td class="num">{{ row.quantity_difference ?? "待核对" }}</td><td class="num">{{ row.amount_difference === null ? "待核对" : money(row.amount_difference) }}</td>
          <td>{{ RECON_STATES[row.state] ?? row.state }}</td>
        </tr></tbody>
      </table></div>
    </section>
    <WsModal v-if="confirming && preview" title="确认库存科目对照" @close="!saving && (confirming = false)">
      <p>写入公司根目录「库存科目对照.json」并绑定当前账套科目表。确认后 V2 成本、进销存比较与凭证草稿按新对照计算。</p>
      <p class="muted">不执行账套操作，不新建科目；账套科目表变化后需重新确认。</p>
      <div class="actions"><button type="button" class="primary" :disabled="saving" :aria-busy="saving" @click="save">{{ saving ? "保存中…" : "确认保存对照" }}</button><button type="button" :disabled="saving" @click="confirming = false">取消</button></div>
    </WsModal>
  </section>
</template>

<style scoped>
.cost-inventory__group { border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; margin: 8px 0; }
.cost-inventory__group .field { max-width: 240px; }
</style>
