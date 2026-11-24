<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import type { CompareFocus } from "../compareFocus";

// WS-04 detail drawer: where a category's numbers come from, step by step. The steps are text
// built by the backend from the values it computed; the page only shows them.
const props = defineProps<{ focus: CompareFocus; labels: { a: string; b: string } }>();
const emit = defineEmits<{ close: [] }>();
const closeButton = ref<HTMLButtonElement | null>(null);
watch(() => props.focus, () => void nextTick(() => closeButton.value?.focus()), { immediate: true });
</script>

<template>
  <aside class="compare-drawer" role="dialog" aria-modal="false" :aria-label="`${focus.label} 明细`" @keydown.escape="emit('close')">
    <header class="compare-drawer__head">
      <h3>{{ focus.label }}</h3>
      <button ref="closeButton" type="button" class="ws-tab__close" aria-label="关闭明细" @click="emit('close')">×</button>
    </header>
    <p class="muted">来源：{{ labels.a }} {{ focus.record_ids.a.length }} 条，{{ labels.b }} {{ focus.record_ids.b.length }} 条（下方并排列表已只显示这些记录）。</p>
    <ol v-if="focus.steps.length" class="compare-drawer__steps">
      <li v-for="(step, index) in focus.steps" :key="index">{{ step }}</li>
    </ol>
    <p v-else class="muted">这一项没有额外的计算过程。</p>
  </aside>
</template>
