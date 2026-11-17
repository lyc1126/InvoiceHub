<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
import type { CompareRecord } from "../api/types";
import type { CompareFocus } from "../compareFocus";
import { VIEW_ACTIVE } from "../modules";
import { money } from "../format";
import CompareThumbnail from "./CompareThumbnail.vue";
import SourcePreview from "./SourcePreview.vue";

const props = defineProps<{ records: { a: CompareRecord[]; b: CompareRecord[] }; receipts?: CompareRecord[]; labels: { a: string; b: string }; focus: CompareFocus | null }>();
const emit = defineEmits<{ detail: [focus: CompareFocus] }>();
const active = inject(VIEW_ACTIVE, ref(true));
const page = ref(1);
const previewing = ref<CompareRecord | null>(null);
const rows = computed(() => {
  const invoices = (["a", "b"] as const).flatMap((side) => props.records[side]
    .filter((row) => row.invoice_number && (!props.focus || props.focus.record_ids[side].includes(row.id)))
    .map((row) => ({ ...row, key: `${side}:${row.id}`, label: props.labels[side] })));
  const receipts = (props.receipts ?? []).filter((row) => !props.focus || row.detail?.record_ids.b.some((id) => props.focus!.record_ids.b.includes(id)))
    .map((row) => ({ ...row, key: row.id, label: "银行回单" }));
  return [...invoices, ...receipts];
});
const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / 6)));
const visible = computed(() => rows.value.slice((page.value - 1) * 6, page.value * 6));
watch(() => [props.records, props.receipts, props.focus], () => { page.value = 1; previewing.value = null; });
watch(active, (value) => { if (!value) previewing.value = null; });
</script>

<template>
  <section class="compare-gallery" aria-label="原始凭证缩略图">
    <header class="compare-sources__head"><h3>原始凭证</h3><span class="muted">{{ rows.length }} 条 · 点击票面查看大图，点击明细查看识别字段与对应流水</span></header>
    <div class="compare-gallery__grid">
      <article v-for="row in visible" :key="row.key" class="compare-gallery__card">
        <CompareThumbnail v-if="row.preview && active" :record="row" @open="previewing = row" />
        <p v-else class="compare-thumbnail muted">{{ row.preview ? "返回后重新核对票面" : row.label === '银行回单' ? '回单来源不唯一，无法预览' : '原票需先将来源设为监控目录' }}</p>
        <strong>{{ row.invoice_number || row.source_file }}</strong>
        <small>{{ row.label }} · {{ row.invoice_date || "日期未识别" }}</small>
        <span>{{ row.counterpart || "对方未识别" }}</span><span>{{ money(row.amount) }}</span>
        <button v-if="row.detail" type="button" class="link" @click="emit('detail', row.detail)">明细</button>
      </article>
    </div>
    <p v-if="!rows.length" class="muted">当前范围没有可展示的原始凭证。</p>
    <div v-if="pages > 1" class="actions">
      <button type="button" :disabled="page === 1" @click="page -= 1">上一组凭证</button><span>{{ page }} / {{ pages }}</span>
      <button type="button" :disabled="page === pages" @click="page += 1">下一组凭证</button>
    </div>
    <SourcePreview v-if="previewing?.preview && active" :label="previewing.invoice_number || previewing.source_file" :preview="previewing.preview" @close="previewing = null" />
  </section>
</template>
