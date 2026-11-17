<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, provide, ref, watch } from "vue";
import type { Company, CompareRecord, CompareResult } from "../api/types";
import { request } from "../api/client";
import { companySourceKey } from "../stores/companies";
import { VIEW_ACTIVE } from "../modules";
import { errorText, money } from "../format";
import CompareThumbnail from "./CompareThumbnail.vue";
import SourcePreview from "./SourcePreview.vue";
import CompareDrawer from "./CompareDrawer.vue";
import type { CompareFocus } from "../compareFocus";

const props = defineProps<{ company: Company; start: string; end: string; active: boolean }>();
const parentActive = inject(VIEW_ACTIVE, ref(true));
const active = computed(() => parentActive.value && props.active);
provide(VIEW_ACTIVE, active);
type DocumentRow = CompareRecord & { key: string; kind: string; labels: { a: string; b: string } };
const rows = ref<DocumentRow[]>([]);
const filter = ref("all"), page = ref(1), error = ref("");
const loading = ref(false);
const preview = ref<DocumentRow | null>(null), detail = ref<DocumentRow | null>(null);
const filters = [{ id: "all", label: "全部" }, { id: "out", label: "销项发票" }, { id: "in", label: "进项发票" }, { id: "bank", label: "银行回单" }];
const filtered = computed(() => rows.value.filter(row => filter.value === "all" || row.kind === filter.value));
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 6)));
const visible = computed(() => filtered.value.slice((page.value - 1) * 6, page.value * 6));
let generation = 0;
// Each read runs the bank-flow comparison twice. Defer it until the section nears the
// viewport so opening the overview stays as cheap as the KPI/ledger reads above it.
const root = ref<HTMLElement>();
const seen = ref(typeof IntersectionObserver === "undefined");
let observer: IntersectionObserver | undefined;
onMounted(() => {
  if (seen.value || !root.value) return;
  observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) { seen.value = true; observer?.disconnect(); } }, { rootMargin: "240px" });
  observer.observe(root.value);
});
let controller: AbortController | undefined;
async function load(): Promise<void> {
  const mine = ++generation;
  controller?.abort(); controller = new AbortController();
  rows.value = []; preview.value = null; detail.value = null; page.value = 1;
  loading.value = true; error.value = "";
  const pairs = [{ key: "cost_invoice_dir", kind: "in", label: "进项发票" }, { key: "issued_invoice_dir", kind: "out", label: "销项发票" }];
  const results = await Promise.allSettled(pairs.map(pair => {
    const query = new URLSearchParams({ a: pair.key, b: "bank_flow_dir" });
    if (props.start) query.set("start", props.start);
    if (props.end) query.set("end", props.end);
    return request<CompareResult>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/compare?${query}`, { signal: controller!.signal });
  }));
  if (mine !== generation) return;
  const seen = new Set<string>();
  // The comparison service owns source identities and links. Reuse only its preview
  // grants; the gallery never makes a non-monitored invoice previewable by guessing a path.
  results.forEach((result, index) => {
    if (result.status === "rejected") { error.value += `${pairs[index]!.label}：${errorText(result.reason)}；`; return; }
    const value = result.value, pair = pairs[index]!;
    const labels = { a: pair.label, b: "银行流水" };
    for (const record of value.records?.a ?? []) {
      if (record.invoice_number) rows.value.push({ ...record, key: `${pair.kind}:${record.id}`, kind: pair.kind, labels });
    }
    for (const record of value.receipts ?? []) {
      const key = record.preview && "kind" in record.preview && record.preview.kind === "receipt" ? record.preview.receipt_id : record.id;
      if (!seen.has(key)) { seen.add(key); rows.value.push({ ...record, key: `bank:${key}`, kind: "bank", labels }); }
    }
    if (value.state === "unreadable") error.value += `${pair.label}：${value.message}；`;
  });
  loading.value = false;
}
watch([() => `${companySourceKey(props.company)}/${props.company.monitored}/${props.company.monitored_subdir_key}/${props.start}/${props.end}`, seen], ([, visible]) => { if (visible) void load(); }, { immediate: true });
watch(filter, () => { page.value = 1; });
watch(active, value => { if (!value) { preview.value = null; detail.value = null; } });
onBeforeUnmount(() => { ++generation; controller?.abort(); observer?.disconnect(); });
</script>

<template>
  <section ref="root" class="overview-section overview-documents" aria-label="总览原始凭证">
    <header class="overview-section__head"><div><h3>原始凭证</h3><p>共 {{ rows.length }} 份 · 原票与关联流水取自公司核对结果。</p></div>
      <div class="period-segment" role="group" aria-label="凭证类型"><button v-for="item in filters" :key="item.id" type="button" :aria-pressed="filter === item.id" @click="filter = item.id">{{ item.label }}</button></div>
    </header>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}<button type="button" :disabled="loading" @click="load">重试</button></p>
    <div class="overview-doc-grid">
      <article v-for="row in visible" :key="row.key" class="overview-doc">
        <CompareThumbnail v-if="row.preview && active" :record="row" @open="preview = row" />
        <div v-else class="overview-doc__unavailable"><span>{{ row.kind === 'bank' ? '银行回单' : '发票' }}</span><small>{{ row.preview ? '返回后重新核对票面' : '此来源暂无原票预览权限' }}</small></div>
        <div class="overview-doc__meta"><div><span :title="row.counterpart">{{ row.counterpart || row.source_file }}</span><small>{{ row.invoice_date || '日期未识别' }}</small></div><strong>¥{{ money(row.amount) }}</strong><div><span v-if="row.flow_match" class="tag" :class="row.flow_match === 'matched' ? 'pill-ok' : 'pill-warn'">{{ row.flow_match === 'matched' ? '已对流水' : '未对流水' }}</span><small v-if="row.project"> · {{ row.project }}{{ row.project_source === 'manual' ? '（人工）' : '' }}</small></div><div><small>{{ filters.find(item => item.id === row.kind)?.label }}</small><button v-if="row.detail" type="button" class="link" @click="detail = row">识别字段与流水 ›</button></div></div>
      </article>
    </div>
    <p v-if="!visible.length" class="overview-empty">{{ loading ? '正在读取原始凭证…' : error ? '读取未完成，可重试或进入资料目录核对。' : '该筛选下没有可展示的凭证。' }}</p>
    <div v-if="pages > 1" class="actions"><button type="button" :disabled="page === 1" @click="page--">上一组</button><span>{{ page }} / {{ pages }}</span><button type="button" :disabled="page === pages" @click="page++">下一组</button></div>
    <SourcePreview v-if="preview?.preview && active" :label="preview.invoice_number || preview.source_file" :preview="preview.preview" @close="preview = null" />
    <CompareDrawer v-if="detail?.detail && active" :focus="detail.detail as CompareFocus" :labels="detail.labels" @close="detail = null" />
  </section>
</template>
