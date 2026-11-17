<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import { errorText } from "../format";
import { companySourceKey } from "../stores/companies";
import type { Company } from "../api/types";
import WsModal from "./WsModal.vue";
const props = defineProps<{ company: Company }>();
interface Layout { layout_hash: string }
interface Index { revision: number; files: { file_ref: string; name: string }[]; layouts: Record<string, Layout> }
interface Direction { reverse: boolean; sign: number }
interface Preview { sample_rows?: { row: number; values: string[] }[]; columns: string[]; guessed_mapping: Record<string, number>; fields: string[]; layout_hash: string; revision: number; profile_applied: boolean; save_blockers?: string[]; balance_chain: { ok: boolean; direction?: Direction | null; breaks: { row: number | null; message: string }[] } }
const index = ref<Index | null>(null), preview = ref<Preview | null>(null);
const selected = ref<{ file_ref: string; name: string } | null>(null);
const mapping = ref<Record<string, number>>({});
const busy = ref(false), dirty = ref(false), unknown = ref(false), error = ref(""), notice = ref("");
const names: Record<string, string> = { date: "日期", balance: "余额", inflow: "收入", outflow: "支出", amount: "单金额", direction: "借贷标志", counterparty: "对方户名", account: "本方账号", details: "摘要", flow_no: "流水号" };
let generation = 0;
const base = () => `/api/v1/companies/${encodeURIComponent(props.company.id)}/bank-layouts`;
async function load(): Promise<void> {
  const mine = ++generation;
  try { const value = await request<Index>(`${base()}?files=1`); if (mine === generation) index.value = value; }
  catch (cause) { if (mine === generation) error.value = errorText(cause); }
}
async function inspect(file: { file_ref: string; name: string }, changed = false): Promise<void> {
  const mine = ++generation;
  if (!changed) preview.value = null;
  selected.value = file; busy.value = true; error.value = "";
  try {
    const value = await request<Preview>(`${base()}/preview`, { method: "POST", body: { file_ref: file.file_ref, ...(changed ? { mapping: mapping.value } : {}) } });
    if (mine !== generation) return;
    preview.value = value; mapping.value = { ...value.guessed_mapping }; dirty.value = false;
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) busy.value = false; }
}
// Labels only explain where a column guess came from; the balance chain from the
// server stays the sole authority for direction (prototype: 借贷方向不靠词典).
const fieldOf = (index: number): string => Object.keys(mapping.value).find(key => mapping.value[key] === index) ?? "";
function chipOf(index: number): ["ok" | "warn", string] {
  const field = fieldOf(index);
  if (!field) return ["warn", "未使用"];
  if (["inflow", "outflow", "amount", "direction"].includes(field)) return ["warn", "方向由余额链确认"];
  if (preview.value?.guessed_mapping[field] !== index) return ["ok", "手动指定"];
  return ["ok", preview.value.profile_applied ? "已确认版式" : "表头词典命中"];
}
const directionText = (direction?: Direction | null): string => !direction ? "方向唯一" :
  `${direction.reverse ? "倒序排列" : "顺序排列"}，${direction.sign === 1 ? "收支方向与所选列一致" : "收支方向与所选列相反"}`;
const savable = computed(() => !!preview.value && !busy.value && !unknown.value && !dirty.value &&
  preview.value.balance_chain.ok && !preview.value.save_blockers?.length);
function assign(index: number, value: string): void {
  const next = { ...mapping.value };
  for (const key in next) if (next[key] === index) delete next[key];
  if (value) next[value] = index;
  mapping.value = next; dirty.value = true;
}
async function save(): Promise<void> {
  if (!savable.value || !preview.value) return;
  const mine = ++generation;
  busy.value = true; error.value = "";
  try {
    await request(base(), { method: "POST", body: { mapping: mapping.value, layout_hash: preview.value.layout_hash, revision: preview.value.revision } });
    if (mine !== generation) return;
    selected.value = null; notice.value = "版式已保存，后续同版式文件会自动校验并套用。";
    await load();
  } catch (cause) {
    if (mine === generation) { error.value = errorText(cause); unknown.value = !(cause instanceof ApiError && cause.status >= 400 && cause.status < 500); }
  } finally { busy.value = false; }
}
async function query(): Promise<void> {
  const mine = ++generation;
  try {
    const value = await request<Index>(base());
    if (mine !== generation) return;
    if (Object.values(value.layouts).some(layout => layout.layout_hash === preview.value?.layout_hash)) {
      unknown.value = false; selected.value = null; notice.value = "已查询确认版式保存成功。"; await load();
    } else error.value = "尚未查询到该次保存结果，请继续核对；不会重复提交。";
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
}
watch(() => companySourceKey(props.company, ["bank_flow_dir"]), () => { selected.value = null; preview.value = null; unknown.value = false; busy.value = false; void load(); }, { immediate: true });
onBeforeUnmount(() => { ++generation; });
</script>
<template>
  <section class="overview-section" aria-label="银行版式">
    <header class="overview-section__head"><div><h3>银行版式</h3><p>按内容确认列映射；余额链全部成立后才能保存。支持 CSV、单表 XLSX 与可还原表格的文字 PDF。</p></div><button type="button" :disabled="busy || unknown" @click="load">重新列出文件</button></header>
    <button v-if="unknown && !selected" type="button" @click="query">查询保存结果</button>
    <p v-if="error && !selected" class="banner banner--error" role="alert">{{ error }}</p><p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <div class="overview-table-wrap"><table class="grid"><thead><tr><th>银行流水文件</th><th>操作</th></tr></thead><tbody><tr v-for="file in index?.files ?? []" :key="file.file_ref"><td>{{ file.name }}</td><td><button type="button" :disabled="busy || unknown" @click="inspect(file)">确认列映射</button></td></tr><tr v-if="!index?.files.length"><td colspan="2">没有可读取的银行文件。</td></tr></tbody></table></div>
    <WsModal :open="!!selected" :title="`确认列映射 · ${selected?.name ?? ''}`" wide @close="selected = null">
      <p class="overview-notice">方向由连续余额判定，不能仅凭“借方 / 贷方”列名。首行期初由首笔倒推，仍需核对原对账单。</p>
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
      <p v-if="busy" role="status">读取中…</p>
      <!-- Prototype openMapping: one select per column above the original header, then sample rows. -->
      <div v-if="preview" class="overview-table-wrap"><table class="grid map-table"><thead>
        <tr><th>原始行</th><th v-for="(column, i) in preview.columns" :key="i"><select :aria-label="`${column} 映射`" :disabled="busy || unknown" :value="fieldOf(i)" @change="assign(i, ($event.target as HTMLSelectElement).value)"><option value="">不使用</option><option v-for="field in preview.fields" :key="field" :value="field">{{ names[field] ?? field }}</option></select><small><span class="chip" :class="`chip--${chipOf(i)[0]}`">{{ chipOf(i)[1] }}</span></small></th></tr>
        <tr><th class="muted">#</th><th v-for="(column, i) in preview.columns" :key="i" class="muted">{{ column }}</th></tr>
      </thead><tbody><tr v-for="row in preview.sample_rows ?? []" :key="row.row"><td class="muted">{{ row.row }}</td><td v-for="(value, i) in row.values" :key="i">{{ value }}</td></tr><tr v-if="!preview.sample_rows?.length"><td :colspan="preview.columns.length + 1" class="muted">没有可展示的样例行。</td></tr></tbody></table></div>
      <template v-if="preview">
        <h4 class="map-heading">方向判定（余额链）</h4>
        <div class="checkline" :class="{ bad: dirty || !preview.balance_chain.ok }">{{ dirty ? '! 映射已改变，请重新校验。' : preview.balance_chain.ok ? `✓ ${directionText(preview.balance_chain.direction)}：余额链全部成立` : '✗ 余额链未通过或方向不唯一，禁止保存' }}</div>
        <p v-for="(point, i) in preview.balance_chain.breaks" :key="`b${i}`" class="map-break">{{ point.row ? `第 ${point.row} 行：` : '' }}{{ point.message }}</p>
        <div v-for="(message, i) in preview.save_blockers ?? []" :key="`s${i}`" class="checkline bad">✗ {{ message }}</div>
      </template>
      <div class="actions"><button v-if="selected" type="button" :disabled="busy || unknown" @click="inspect(selected, true)">校验映射</button><button type="button" class="primary" :disabled="!savable" :aria-busy="busy" @click="save">确认并保存为版式档案</button><button v-if="unknown" type="button" @click="query">查询保存结果</button></div>
    </WsModal>
  </section>
</template>

<style scoped>
/* Prototype .map-table / .chip / .checkline, rebuilt on shared tokens for dark skins. */
.overview-table-wrap .map-table { min-width: 0; }
.map-table th select { width: 100%; min-width: 104px; min-height: 30px; font-size: 13px; }
.map-table th small { display: block; margin-top: 3px; font-weight: 400; font-size: 11px; }
.chip { display: inline-block; padding: 0 6px; border-radius: 3px; font-size: 11px; font-weight: 600; }
.chip--ok { color: var(--green); background: var(--ws-success-bg); }
.chip--warn { color: var(--amber); background: color-mix(in srgb, var(--amber) 9%, var(--surface)); }
.map-heading { margin: 14px 0 4px; font-size: 14px; }
.checkline { display: flex; align-items: center; gap: 8px; padding: 8px 12px; margin-top: 10px; border: 1px solid color-mix(in srgb, var(--green) 25%, var(--surface)); border-radius: 4px; background: var(--ws-success-bg); color: var(--green); font-size: 13px; font-variant-numeric: tabular-nums; }
.checkline.bad { border-color: color-mix(in srgb, var(--red) 30%, var(--surface)); background: color-mix(in srgb, var(--red) 7%, var(--surface)); color: var(--red); }
.map-break { margin: 6px 0 0; font-size: 12.5px; color: var(--red); }
</style>
