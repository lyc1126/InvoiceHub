<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import { costBase } from "../api/costV2";
import type { Company } from "../api/types";
import { companySourceKey } from "../stores/companies";
import { errorText } from "../format";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

type Kind = "goods" | "service" | "expense" | "fixed_asset";
interface Item { name: string; standard_name: string; type: Kind; sources: string[] }
interface Payload { revision: string; items: Item[] }
interface Preview { preview_hash: string; changes: { name: string; before: Kind; after: Kind }[] }
const props = defineProps<{ company: Company; saved: number }>();
const emit = defineEmits<{ changed: [] }>();
const labels: Record<Kind, string> = { goods: "货物", service: "服务", expense: "费用", fixed_asset: "固定资产" };
const open = ref(false), busy = ref(false), unknown = ref(false), stale = ref(false);
const data = ref<Payload | null>(null), types = ref<Record<string, Kind>>({}), error = ref("");
const preview = ref<{ result: Preview; body: { revision: string; types: Record<string, Kind> } } | null>(null);
const dirty = computed(() => data.value?.items.some(row => types.value[row.name] !== row.type) ?? false);
let generation = 0;
let previewEpoch = 0;
async function load(): Promise<void> {
  const mine = ++generation;
  busy.value = true;
  try {
    const result = await request<Payload>(`${costBase(props.company.id)}/item-types`);
    if (mine !== generation) return;
    data.value = result;
    types.value = Object.fromEntries(result.items.map(row => [row.name, row.type]));
    preview.value = null; unknown.value = false; stale.value = false; error.value = "";
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) busy.value = false; }
}
function launch(): void { open.value = true; if (!dirty.value || unknown.value) void load(); }
function change(item: Item, event: Event): void {
  const kind = (event.target as HTMLSelectElement).value as Kind;
  for (const row of data.value?.items ?? []) if (row.standard_name === item.standard_name) types.value[row.name] = kind;
  generation += 1; preview.value = null;
}
async function runPreview(): Promise<void> {
  if (!data.value || stale.value || unknown.value) return;
  const mine = ++generation, epoch = ++previewEpoch, company = props.company.id;
  const body = { revision: data.value.revision, types: { ...types.value } };
  busy.value = true;
  try {
    const result = await request<Preview>(`${costBase(company)}/item-types/preview`, { method: "POST", body });
    if (mine === generation && epoch === previewEpoch) { preview.value = { result, body }; error.value = ""; }
  } catch (cause) {
    if (mine !== generation) return;
    if (cause instanceof ApiError && cause.status === 409) { await load(); }
    error.value = errorText(cause);
  } finally { if (mine === generation) busy.value = false; }
}
async function save(): Promise<void> {
  if (!preview.value || busy.value || unknown.value) return;
  const mine = ++generation, current = preview.value;
  busy.value = true;
  try {
    await request(`${costBase(props.company.id)}/item-types`, { method: "PUT", body: { ...current.body, preview_hash: current.result.preview_hash, confirm: true } });
    if (mine !== generation) return;
    preview.value = null; open.value = false;
    data.value = null;
    toast("品目类型已保存。"); emit("changed");
  } catch (cause) {
    if (mine !== generation) return;
    preview.value = null;
    if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
      if (cause.status === 409) await load();
      error.value = errorText(cause);
    } else { unknown.value = true; error.value = "归类保存结果待核对，请读取结果；不会自动重发。"; }
  } finally { if (mine === generation) busy.value = false; }
}
watch(() => props.saved, () => {
  previewEpoch += 1;
  preview.value = null;
  if (open.value) { if (dirty.value) stale.value = true; else void load(); }
});
watch(() => companySourceKey(props.company, ["cost_invoice_dir", "issued_invoice_dir"]), () => {
  generation += 1; open.value = false; data.value = null; preview.value = null; types.value = {};
  error.value = ""; busy.value = false; unknown.value = false; stale.value = false;
});
onBeforeUnmount(() => { generation += 1; });
</script>

<template>
  <button type="button" @click="launch">品目类型与服务收入…</button>
  <WsModal v-if="open" title="品目类型与服务收入" wide @close="!busy && (open = false)">
    <p class="overview-notice">将服务销项的品名明确标记为“服务”，再按月份与项目匹配人工成本。同一标准名称的别名一起归类；不会把费用或固定资产当作服务。</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="stale" class="banner banner--note">来源已更新，草稿保留；请放弃草稿并重新读取后预览。</p>
    <button v-if="unknown || stale" type="button" :disabled="busy" @click="load">{{ unknown ? "读取保存结果" : "放弃草稿并重新读取" }}</button>
    <div class="overview-table-wrap"><table class="grid" aria-label="品目类型">
      <thead><tr><th>票面品名</th><th>标准名称</th><th>来源</th><th>类型</th></tr></thead>
      <tbody><tr v-for="row in data?.items ?? []" :key="row.name"><td>{{ row.name }}</td><td>{{ row.standard_name }}</td><td>{{ row.sources.join(" / ") }}</td>
        <td><select :value="types[row.name]" :aria-label="`类型 ${row.name}`" :disabled="busy || unknown || stale" @change="change(row, $event)"><option v-for="(label, key) in labels" :key="key" :value="key">{{ label }}</option></select></td>
      </tr><tr v-if="!data?.items.length"><td colspan="4">{{ busy ? "读取中…" : "没有已汇总品目。" }}</td></tr></tbody>
    </table></div>
    <p class="muted">确认会更新本公司的品目表和兼容工作簿，服务退出货物开票参考与库存。旧已开快照保留，不生成凭证。</p>
    <ul v-if="preview"><li v-for="row in preview.result.changes" :key="row.name">{{ row.name }}：{{ labels[row.before] }} → {{ labels[row.after] }}</li></ul>
    <div class="actions"><button type="button" :disabled="!data || !dirty || busy || unknown || stale" :aria-busy="busy" @click="runPreview">预览归类</button>
      <button type="button" class="primary" :disabled="!preview || busy || unknown || stale" :aria-busy="busy" @click="save">确认保存归类</button>
      <button type="button" :disabled="busy" @click="open = false">取消</button></div>
  </WsModal>
</template>
