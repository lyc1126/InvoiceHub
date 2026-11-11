<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { request } from "../api/client";
import type { Company, CompareResult } from "../api/types";
import { errorText } from "../format";
import CompanyDeductionResult from "./CompanyDeductionResult.vue";
import CompanyInventoryResult from "./CompanyInventoryResult.vue";

const props = defineProps<{ company: Company }>();
// Folder pairs with a reconciliation relation; the backend refuses any other pair.
const RELATIONS = [
  { id: "deduction", label: "成本发票 ⇄ 进项抵扣（勾选清单）", a: "cost_invoice_dir", b: "input_deduction_dir" },
  { id: "inventory", label: "成本发票 ⇄ 开具发票（进销存）", a: "cost_invoice_dir", b: "issued_invoice_dir" },
] as const;

const filters = reactive({ relation: RELATIONS[0].id as string, start: "", end: "" });
const result = ref<CompareResult | null>(null);
const loading = ref(false);
const error = ref("");
const relation = computed(() => RELATIONS.find((item) => item.id === filters.relation) ?? RELATIONS[0]);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams({ a: relation.value.a, b: relation.value.b });
  if (filters.start) query.set("start", filters.start);
  if (filters.end) query.set("end", filters.end);
  try {
    result.value = await request<CompareResult>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/compare?${query}`);
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    loading.value = false;
  }
}

// Switching the relation runs the new comparison right away; the old result is not reused.
watch(
  () => filters.relation,
  () => void load(),
);

watch(
  () => props.company.id,
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
      <template v-if="(result.state === 'ok' || result.state === 'no_lists' || result.state === 'no_details') && result.relation === filters.relation">
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

        <CompanyDeductionResult v-if="result.relation === 'deduction'" :result="result" />
        <CompanyInventoryResult v-else :result="result" />
      </template>
    </template>
  </section>
</template>
