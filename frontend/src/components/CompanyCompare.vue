<script setup lang="ts">
import { companySourceKey } from "../stores/companies";
import { computed, inject, onBeforeUnmount, provide, reactive, ref, watch } from "vue";
import { VIEW_ACTIVE } from "../modules";
import { request } from "../api/client";
import type { Company, CompareResult } from "../api/types";
import { errorText } from "../format";
import { COMPARE_FOCUS, type CompareFocus } from "../compareFocus";
import { RELATIONS } from "../relations";
import CompareDrawer from "./CompareDrawer.vue";
import CompareSources from "./CompareSources.vue";
import CompareGallery from "./CompareGallery.vue";
import CompanyDeductionResult from "./CompanyDeductionResult.vue";
import CompanyInventoryResult from "./CompanyInventoryResult.vue";
import CompanySettlementResult from "./CompanySettlementResult.vue";

// `relation` presets the pair when the page is opened from the sidebar's "与已选项进行比较".
const props = withDefaults(defineProps<{ company: Company; relation?: string; active?: boolean; compactInventory?: boolean }>(), { active: true });
const parentActive = inject(VIEW_ACTIVE, ref(true));
provide(VIEW_ACTIVE, computed(() => parentActive.value && props.active));

// The backend names the two settlement sides one relation; the page keeps them apart.
function relationOf(item: CompareResult): string {
  return item.relation === "settlement" ? (item.side ?? "") : item.relation;
}

const filters = reactive({ relation: (props.relation || RELATIONS[0].id) as string, start: "", end: "" });
const result = ref<CompareResult | null>(null);
const loading = ref(false);
const error = ref("");
const relation = computed(() => RELATIONS.find((item) => item.id === filters.relation) ?? RELATIONS[0]);

// WS-04: the clicked category; the drawer explains it and the source lists narrow to it.
const focus = ref<CompareFocus | null>(null);
provide(COMPARE_FOCUS, (next: CompareFocus) => {
  focus.value = next;
});
const labels = computed(() => {
  const name = (key: string) => props.company.subdirs.find((item) => item.key === key)?.label ?? key;
  return { a: name(relation.value.a), b: name(relation.value.b) };
});

let loadGeneration = 0;
async function load(): Promise<void> {
  const mine = ++loadGeneration;
  focus.value = null;
  result.value = null;
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams({ a: relation.value.a, b: relation.value.b });
  if (filters.start) query.set("start", filters.start);
  if (filters.end) query.set("end", filters.end);
  try {
    const next = await request<CompareResult>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/compare?${query}`);
    if (mine !== loadGeneration) return;
    result.value = next;
  } catch (cause) {
    if (mine === loadGeneration) error.value = errorText(cause);
  } finally {
    if (mine === loadGeneration) loading.value = false;
  }
}

// Switching the relation runs the new comparison right away; the old result is not reused.
watch(
  () => filters.relation,
  () => void load(),
);
onBeforeUnmount(() => { loadGeneration += 1; });

watch(
  () => `${companySourceKey(props.company)}/${props.company.monitored_subdir_key}/${props.company.monitored}`,
  () => {
    result.value = null;
    void load();
  },
  { immediate: true },
);
</script>

<template>
  <section aria-label="勾稽">
    <form class="toolbar" @submit.prevent="load">
      <select v-model="filters.relation" aria-label="比较关系">
        <option v-for="item in RELATIONS" :key="item.id" :value="item.id">{{ item.label }}</option>
      </select>
      <input v-model="filters.start" type="month" aria-label="开始月份">
      <span class="muted">至</span>
      <input v-model="filters.end" type="month" aria-label="结束月份">
      <button type="submit" :disabled="loading" :aria-busy="loading">{{ loading ? "核对中…" : "核对" }}</button>
    </form>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

    <template v-if="result">
      <p v-if="result.state !== 'ok'" class="banner" :class="result.state === 'unreadable' ? 'banner--error' : 'banner--note'" role="status">
        {{ result.message }}
      </p>
      <!-- A stale result from the other relation must not render while the new one loads. -->
      <template v-if="(result.state === 'ok' || result.state === 'no_lists' || result.state === 'no_details' || result.state === 'no_statements') && relationOf(result) === filters.relation">
        <p v-if="result.basis_label" class="banner banner--note">{{ result.basis_label }}</p>
        <details class="checks" :class="{ 'checks--failed': !result.checks_ok }" :open="!result.checks_ok" role="status">
          <summary><strong>{{ result.checks_ok ? `核对校验全部成立（${result.checks?.length ?? 0} 项）` : "核对校验不成立" }}</strong></summary>
          <ul>
            <li v-for="check in result.checks" :key="check.code" :class="{ 'check--failed': !check.ok }">
              {{ check.ok ? "✓" : "✗" }} {{ check.message }}
            </li>
          </ul>
        </details>
        <ul v-if="result.warnings?.length" class="warnings warnings--compact">
          <li v-for="warning in result.warnings" :key="warning.code">{{ warning.message }}</li>
        </ul>
        <div v-if="result.summary_details?.length" class="compare-summary" aria-label="比较汇总">
          <button v-for="item in result.summary_details" :key="item.label" type="button" class="compare-summary__card" @click="focus = item">
            <span>{{ item.label }}</span><strong>{{ item.value }}</strong><small>查看来源与计算过程</small>
          </button>
        </div>

        <CompanyDeductionResult v-if="result.relation === 'deduction'" :result="result" />
        <CompanyInventoryResult v-else-if="result.relation === 'inventory'" :result="result" :compact="compactInventory" />
        <CompanySettlementResult v-else :result="result" />
        <CompareGallery v-if="result.records" :records="result.records" :receipts="result.receipts" :labels="labels" :focus="focus" @detail="focus = $event" />
        <CompareSources v-if="result.records" :records="result.records" :labels="labels" :focus="focus" @clear="focus = null" @detail="focus = $event" />
        <CompareDrawer v-if="focus" :focus="focus" :labels="labels" @close="focus = null" />
      </template>
    </template>
  </section>
</template>
