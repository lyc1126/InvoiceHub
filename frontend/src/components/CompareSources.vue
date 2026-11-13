<script setup lang="ts">
import { computed, ref } from "vue";
import type { CompareRecord } from "../api/types";
import type { CompareFocus } from "../compareFocus";
import { money } from "../format";
import SourcePreview from "./SourcePreview.vue";

// WS-04: the two folders' source records side by side. With a category in focus both lists keep
// only that category's records (ids come from the backend); "显示全部" clears the focus.
const props = defineProps<{ records: { a: CompareRecord[]; b: CompareRecord[] }; labels: { a: string; b: string }; focus: CompareFocus | null }>();
const emit = defineEmits<{ clear: [] }>();

const sides = computed(() =>
  (["a", "b"] as const).map((side) => {
    const all = props.records[side];
    const wanted = props.focus ? new Set(props.focus.record_ids[side]) : null;
    const rows = wanted ? all.filter((row) => wanted.has(row.id)) : all;
    return { side, label: props.labels[side], all: all.length, rows, previewable: all.some((row) => row.preview) };
  }),
);
// Only records the backend marked (monitored folder, settled list) open the original invoice.
const previewing = ref<CompareRecord | null>(null);
</script>

<template>
  <section class="compare-sources" aria-label="原始记录并排">
    <header class="compare-sources__head">
      <h3>原始记录</h3>
      <p v-if="focus" class="muted" role="status">
        只显示与“{{ focus.label }}”相关的记录
        <button type="button" class="link" @click="emit('clear')">显示全部</button>
      </p>
    </header>
    <div class="compare-sources__cols">
      <div v-for="column in sides" :key="column.side" class="compare-sources__col">
        <h4>{{ column.label }} <span class="muted">{{ column.rows.length }}<template v-if="focus"> / {{ column.all }}</template> 条</span></h4>
        <table class="grid" :aria-label="`${column.label} 原始记录`">
          <thead><tr><th>日期</th><th>号码 / 摘要</th><th>对方</th><th class="num">金额</th><th v-if="column.previewable"><span class="sr-only">原票</span></th></tr></thead>
          <tbody>
            <tr v-for="row in column.rows" :key="row.id">
              <td class="nowrap">{{ row.invoice_date || "—" }}</td>
              <td :title="row.source_file">{{ row.invoice_number || row.details || row.source_file }}</td>
              <td>{{ row.counterpart || "—" }}</td>
              <td class="num">{{ money(row.amount) }}</td>
              <td v-if="column.previewable" class="nowrap">
                <button v-if="row.preview" type="button" class="link" :aria-label="`原票 ${row.invoice_number || row.source_file}`" @click="previewing = row">原票</button>
              </td>
            </tr>
            <tr v-if="!column.rows.length"><td :colspan="column.previewable ? 5 : 4" class="muted">没有记录</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <SourcePreview v-if="previewing?.preview" :label="previewing.invoice_number || previewing.source_file" :preview="previewing.preview" @close="previewing = null" />
  </section>
</template>
