<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import { errorText } from "../format";
import { companySourceKey } from "../stores/companies";
import type { Company } from "../api/types";
import WsModal from "./WsModal.vue";
const props = withDefaults(defineProps<{ company: Company; dirKey?: string }>(), { dirKey: "bank_flow_dir" });
interface Layout { layout_hash: string }
interface Recognition { kind: string; rows: number | null; chain_ok: boolean | null; breaks: { row: string | number | null; message: string }[]; footer: { ok: boolean | null; message: string }; message: string }
interface BankFile { file_ref: string; name: string; recognition?: Recognition }
interface Index { revision: number; files: BankFile[]; layouts: Record<string, Layout>; recognition_complete?: boolean }
interface Direction { reverse: boolean; sign: number }
interface Preview { account_fixed?: string; sample_rows?: { row: number; values: string[] }[]; columns: string[]; guessed_mapping: Record<string, number>; fields: string[]; layout_hash: string; revision: number; profile_applied: boolean; save_blockers?: string[]; balance_chain: { ok: boolean; direction?: Direction | null; breaks: { row: number | null; message: string }[] } }
const index = ref<Index | null>(null), preview = ref<Preview | null>(null);
const selected = ref<{ file_ref: string; name: string } | null>(null);
const mapping = ref<Record<string, number>>({});
const account = ref("");
const recognitionLabel: Record<string, string> = { builtin: "内置版式", confirmed: "已确认版式", unrecognized: "未识别", receipt: "电子回单", unavailable: "待核对" };
const busy = ref(false), dirty = ref(false), unknown = ref(false), error = ref(""), notice = ref("");
const names: Record<string, string> = { date: "日期", balance: "余额", inflow: "收入", outflow: "支出", amount: "单金额", direction: "借贷标志", counterparty: "对方户名", account: "本方账号", details: "摘要", flow_no: "流水号" };
let generation = 0;
const base = () => `/api/v1/companies/${encodeURIComponent(props.company.id)}/bank-layouts`;
async function load(): Promise<void> {
  const mine = ++generation;
  busy.value = true;
  try {
    const query = props.dirKey && props.dirKey !== "bank_flow_dir" ? `?files=1&dir_key=${encodeURIComponent(props.dirKey)}` : "?files=1";
    const value = await request<Index>(`${base()}${query}`);
    if (mine === generation) index.value = value;
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) busy.value = false; }
}
async function inspect(file: { file_ref: string; name: string }, changed = false): Promise<void> {
  const mine = ++generation;
  if (!changed) preview.value = null;
  selected.value = file; busy.value = true; error.value = "";
  try {
    const value = await request<Preview>(`${base()}/preview`, { method: "POST", body: { file_ref: file.file_ref, ...(changed ? { mapping: mapping.value, account_fixed: account.value } : {}) } });
    if (mine !== generation) return;
    preview.value = value; mapping.value = { ...value.guessed_mapping }; account.value = value.account_fixed ?? ""; dirty.value = false;
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
    await request(base(), { method: "POST", body: { mapping: mapping.value, account_fixed: account.value, layout_hash: preview.value.layout_hash, revision: preview.value.revision } });
    if (mine !== generation) return;
    selected.value = null; notice.value = "版式已保存，后续同版式文件会自动校验并套用。";
    await load();
  } catch (cause) {
    if (mine === generation) { error.value = errorText(cause); unknown.value = !(cause instanceof ApiError && cause.status >= 400 && cause.status < 500); }
  } finally { if (mine === generation) busy.value = false; }
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
watch(() => companySourceKey(props.company, [props.dirKey]), () => { selected.value = null; preview.value = null; unknown.value = false; busy.value = false; void load(); }, { immediate: true });
onBeforeUnmount(() => { ++generation; });
</script>
<template>
  <section class="overview-section" aria-label="银行版式">
    <header class="overview-section__head"><div><h3>银行版式</h3><p>按内容确认列映射；余额链全部成立后才能保存。支持 CSV、单表 XLSX 与可还原表格的文字 PDF。</p></div><button type="button" :disabled="busy || unknown" @click="load">重新列出文件</button></header>
    <button v-if="unknown && !selected" type="button" @click="query">查询保存结果</button>
    <p v-if="error && !selected" class="banner banner--error" role="alert">{{ error }}</p><p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <p v-if="busy && !selected" role="status">正在识别文件…</p>
    <p v-if="index?.recognition_complete === false" class="overview-notice">部分文件达到本次数量或时间上限，刷新可继续识别；待核对不表示空文件。</p>
    <div class="overview-table-wrap"><table class="grid"><thead><tr><th>银行流水文件</th><th>版式识别</th><th class="num">行数</th><th>余额链</th><th>页脚合计</th><th>操作</th></tr></thead><tbody>
      <tr v-for="file in index?.files ?? []" :key="file.file_ref"><td>{{ file.name }}<details v-if="file.recognition?.message || file.recognition?.breaks.length"><summary>核对说明</summary><p>{{ file.recognition.message }}</p><p v-for="(point, i) in file.recognition.breaks" :key="i">{{ point.row ? `第 ${point.row} 行：` : '' }}{{ point.message }}</p></details></td>
        <td><span class="tag" :class="file.recognition?.kind === 'unrecognized' ? 'pill-warn' : ''">{{ recognitionLabel[file.recognition?.kind ?? 'unrecognized'] }}</span></td><td class="num">{{ file.recognition?.rows ?? '—' }}</td>
        <td :class="{ 'check--failed': file.recognition?.chain_ok === false }">{{ file.recognition?.chain_ok === true ? '成立' : file.recognition?.chain_ok === false ? '不成立' : '未核对' }}</td><td :class="{ 'check--failed': file.recognition?.footer.ok === false }">{{ file.recognition?.footer.message ?? '未核对' }}</td>
        <td><button v-if="!file.recognition || file.recognition.kind === 'unrecognized'" type="button" :disabled="busy || unknown" @click="inspect(file)">确认列映射</button><span v-else class="muted">—</span></td></tr>
      <tr v-if="index && !index.files.length"><td colspan="6">没有可读取的银行文件。</td></tr></tbody></table></div>
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
        <label class="field">手填本方账号（没有账号列时填写）<input v-model="account" aria-label="手填本方账号" maxlength="64" :disabled="busy || unknown" @input="dirty = true"></label>
        <p class="overview-notice">账号只存本公司版式档案，保留前导零；档案含业务资料，不可分享。文件若有账号列，必须与手填账号一致。</p>
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
