<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import { costBase } from "../api/costV2";
import type { Company } from "../api/types";
import { errorText, money } from "../format";
import { toast } from "../toast";
import { companySourceKey } from "../stores/companies";
import WsModal from "./WsModal.vue";
import CostItemTypes from "./CostItemTypes.vue";

interface ServiceCost { month: string; project: string; amount: string; source: string }
interface Payload { revision: number; source_revision: string; costs: Record<string, ServiceCost>; basis_label: string }
interface Preview { preview_hash: string; before: Record<string, ServiceCost>; after: Record<string, ServiceCost> }

const props = defineProps<{ company: Company; saved: number }>();
const emit = defineEmits<{ changed: [] }>();
const data = ref<Payload | null>(null);
const rows = ref<{ id: string; value: ServiceCost }[]>([]);
const preview = ref<{ body: Record<string, unknown>; result: Preview } | null>(null);
const confirming = ref(false);
const loading = ref(false);
const saving = ref(false);
const unknown = ref(false);
const edited = ref(false);
const stale = ref(false);
const error = ref("");
const base = computed(() => `${costBase(props.company.id)}/service-costs`);
const changes = computed(() => {
  if (!preview.value) return [];
  const { before, after } = preview.value.result;
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].sort().flatMap(id => {
    const old = before[id], next = after[id];
    if (JSON.stringify(old) === JSON.stringify(next)) return [];
    return [{ id, kind: !old ? "新增" : !next ? "删除" : "修改", row: (next ?? old)! }];
  });
});
let generation = 0;
let previewEpoch = 0;

function reset(payload: Payload): void { rows.value = Object.entries(payload.costs).map(([id, value]) => ({ id, value: { ...value } })); }
function touch(): void { previewEpoch += 1; preview.value = null; edited.value = true; }
function add(): void { rows.value.push({ id: `s-${Date.now().toString(36)}${rows.value.length}`, value: { month: "", project: "", amount: "", source: "" } }); touch(); }
function remove(index: number): void { rows.value.splice(index, 1); touch(); }

async function load(): Promise<void> {
  const mine = ++generation;
  loading.value = true;
  try {
    const result = await request<Payload>(base.value, { timeoutMs: 120_000 });
    if (mine !== generation) return;
    data.value = result;
    reset(result);
    edited.value = false; stale.value = false;
    previewEpoch += 1;
    preview.value = null;
    // Only a successful read-back after an unknown write may unlock saving again.
    unknown.value = false;
    error.value = "";
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) { loading.value = false; saving.value = false; } }
}

function validate(): string {
  for (const [index, row] of rows.value.entries()) {
    if (!/^\d{4}-\d{2}$/.test(row.value.month)) return `第 ${index + 1} 行须选择月份。`;
    if (!/^(?:0|[1-9]\d{0,14})(?:\.\d{1,2})?$/.test(row.value.amount.trim())) return `第 ${index + 1} 行金额须为非负数，最多两位小数。`;
    if (!row.value.source.trim()) return `第 ${index + 1} 行须填写成本来源说明。`;
  }
  return "";
}

async function runPreview(): Promise<void> {
  if (!data.value || unknown.value || stale.value) return;
  const mine = generation, epoch = ++previewEpoch;
  const problem = validate();
  if (problem) { error.value = problem; return; }
  const costs = Object.fromEntries(rows.value.map(row => [row.id, { month: row.value.month, project: row.value.project.trim(), amount: row.value.amount.trim(), source: row.value.source.trim() }]));
  const body = { revision: data.value.revision, source_revision: data.value.source_revision, costs };
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
    toast(result.changed ? "服务成本已保存。" : "服务成本没有变化，未写入。");
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
      error.value = "服务成本保存结果待核对，请读取保存结果；不会自动重发。";
    }
  } finally { if (mine === generation) saving.value = false; }
}

watch(() => props.saved, () => {
  previewEpoch += 1; preview.value = null; confirming.value = false;
  if (saving.value) { if (edited.value) stale.value = true; return; }
  // A classification save changes the shared source revision. Keep service
  // drafts visible, but never confirm a preview against that older source.
  if (edited.value && !unknown.value) stale.value = true; else void load();
});
watch(() => companySourceKey(props.company, ["cost_invoice_dir", "issued_invoice_dir"]), () => {
  generation += 1; previewEpoch += 1; data.value = null; rows.value = []; preview.value = null;
  confirming.value = false; saving.value = false; unknown.value = false; stale.value = false; edited.value = false; error.value = ""; void load();
}, { immediate: true });
onBeforeUnmount(() => { generation += 1; previewEpoch += 1; });
</script>

<template>
  <section class="cost-service" aria-label="服务成本">
    <CostItemTypes :company="company" :saved="saved" @changed="emit('changed')" />
    <p class="overview-notice">{{ data?.basis_label ?? "按月份/项目人工录入服务成本，不读取工资社保、不自动分摊。" }} 在“毛利分析”中单列显示，不从货物毛利扣除。</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }} <button v-if="unknown" type="button" :disabled="loading" @click="load">读取保存结果</button></p>
    <p v-if="stale" class="banner banner--note">来源已更新，服务成本草稿保留，旧预览已作废。<button type="button" :disabled="loading" @click="load">放弃草稿并重新读取</button></p>
    <div class="overview-table-wrap"><table class="grid" aria-label="服务成本录入">
      <thead><tr><th>月份</th><th>项目（可空）</th><th class="num">金额</th><th>成本来源说明</th><th></th></tr></thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="row.id">
          <td><input v-model="row.value.month" type="month" :aria-label="`月份 ${index + 1}`" :disabled="saving || unknown" @input="touch"></td>
          <td><input v-model="row.value.project" :aria-label="`项目 ${index + 1}`" maxlength="60" :disabled="saving || unknown" @input="touch"></td>
          <td><input v-model="row.value.amount" class="num" :aria-label="`金额 ${index + 1}`" inputmode="decimal" :disabled="saving || unknown" @input="touch"></td>
          <td><input v-model="row.value.source" :aria-label="`来源 ${index + 1}`" placeholder="如 分包结算单、运输合同" :disabled="saving || unknown" @input="touch"></td>
          <td><button type="button" class="ghost" :disabled="saving || unknown" @click="remove(index)">删除</button></td>
        </tr>
        <tr v-if="!rows.length"><td colspan="5" class="muted">{{ loading ? "读取中…" : "还没有录入服务成本。" }}</td></tr>
      </tbody>
    </table></div>
    <div class="actions">
      <!-- Block adding/previewing while reloading after a classification change so a late load cannot wipe the new row. -->
      <button type="button" :disabled="!data || loading || saving || unknown" @click="add">添加一行</button>
      <button type="button" class="primary" :disabled="!data || loading || saving || unknown || stale" :aria-busy="saving" @click="runPreview">预览</button>
      <button type="button" :disabled="!preview || loading || saving || unknown || stale" @click="confirming = true">确认保存…</button>
    </div>
    <template v-if="preview">
      <p v-if="!changes.length" class="muted">与已保存内容相同。</p>
      <div v-else class="overview-table-wrap"><table class="grid" aria-label="服务成本变更">
        <thead><tr><th>变更</th><th>月份</th><th>项目</th><th class="num">金额</th><th>来源</th></tr></thead>
        <tbody><tr v-for="change in changes" :key="change.id"><td>{{ change.kind }}</td><td>{{ change.row.month }}</td><td>{{ change.row.project || "—" }}</td><td class="num">{{ money(change.row.amount) }}</td><td>{{ change.row.source }}</td></tr></tbody>
      </table></div>
    </template>
    <WsModal v-if="confirming && preview" title="确认保存服务成本" @close="!saving && (confirming = false)">
      <p>写入公司根目录「服务成本归集.json」，共 {{ Object.keys(preview.result.after).length }} 条（变更 {{ changes.length }} 条）。</p>
      <p class="muted">只用于毛利分析单列；不生成凭证，不分摊到客户或品目。</p>
      <div class="actions"><button type="button" class="primary" :disabled="saving" :aria-busy="saving" @click="save">{{ saving ? "保存中…" : "确认保存服务成本" }}</button><button type="button" :disabled="saving" @click="confirming = false">取消</button></div>
    </WsModal>
  </section>
</template>
