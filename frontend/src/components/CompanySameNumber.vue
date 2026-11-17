<script setup lang="ts">
import { companySourceKey } from "../stores/companies";
import { computed, inject, onBeforeUnmount, provide, ref, watch } from "vue";
import { VIEW_ACTIVE } from "../modules";
import { request } from "../api/client";
import type { Company, SameNumberResult } from "../api/types";
import type { CompareFocus } from "../compareFocus";
import { errorText, money } from "../format";
import CompareDrawer from "./CompareDrawer.vue";
import CompareSources from "./CompareSources.vue";
import CompareGallery from "./CompareGallery.vue";

// WS-04 same-number check: two invoice folders without a relation (one company or two). The
// backend lists the invoice numbers found on both sides and says whether each is a possible
// duplicate or one transaction seen from both companies; the page links nothing by itself.
const props = withDefaults(defineProps<{ company: Company; dirKey: string; otherCompany: Company; otherDirKey: string; active?: boolean }>(), { active: true });
const parentActive = inject(VIEW_ACTIVE, ref(true));
provide(VIEW_ACTIVE, computed(() => parentActive.value && props.active));
const result = ref<SameNumberResult | null>(null);
const loading = ref(false);
const error = ref("");
const focus = ref<CompareFocus | null>(null);
const labels = computed(() => ({ a: result.value?.sides.a.label ?? "", b: result.value?.sides.b.label ?? "" }));
const counts = computed(() => result.value?.counts);

let loadGeneration = 0;
async function load(): Promise<void> {
  const mine = ++loadGeneration;
  focus.value = null;
  result.value = null;
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams({ a: props.dirKey, b: props.otherDirKey, b_company: props.otherCompany.id });
  try {
    const next = await request<SameNumberResult>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/same-number?${query}`);
    if (mine !== loadGeneration) return;
    result.value = next;
  } catch (cause) {
    if (mine === loadGeneration) error.value = errorText(cause);
  } finally {
    if (mine === loadGeneration) loading.value = false;
  }
}

// Stable source keys ignore metadata refreshes but invalidate a comparison after a mapping changes.
watch(() => `${companySourceKey(props.company, [props.dirKey])}/${companySourceKey(props.otherCompany, [props.otherDirKey])}/${props.company.monitored_subdir_key}/${props.company.monitored}/${props.otherCompany.monitored_subdir_key}/${props.otherCompany.monitored}`, () => { result.value = null; void load(); }, { immediate: true });
onBeforeUnmount(() => { loadGeneration += 1; });
</script>

<template>
  <section aria-label="同号检查">
    <div class="toolbar">
      <button type="button" :disabled="loading" :aria-busy="loading" @click="load">{{ loading ? "检查中…" : "重新检查" }}</button>
    </div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <template v-if="result">
      <p v-if="result.state !== 'ok'" class="banner banner--note" role="status">{{ result.message }}</p>
      <template v-if="result.state !== 'missing_dir' && counts">
        <p class="banner banner--note">{{ result.basis_label }}</p>
        <details class="checks" :class="{ 'checks--failed': !result.checks_ok }" :open="!result.checks_ok" role="status">
          <summary><strong>{{ result.checks_ok ? `核对校验全部成立（${result.checks?.length ?? 0} 项）` : "核对校验不成立" }}</strong></summary>
          <ul>
            <li v-for="check in result.checks" :key="check.code" :class="{ 'check--failed': !check.ok }">{{ check.ok ? "✓" : "✗" }} {{ check.message }}</li>
          </ul>
        </details>
        <ul v-if="result.warnings?.length" class="warnings warnings--compact">
          <li v-for="warning in result.warnings" :key="warning.code">{{ warning.message }}</li>
        </ul>
        <p :class="counts.duplicate ? 'check--failed' : ''" role="status">
          两边同号 {{ counts.matched }} 张：疑似重复 {{ counts.duplicate }} 张，双方同一张票 {{ counts.pair }} 张<template v-if="counts.amount_differs">，其中金额不同 {{ counts.amount_differs }} 张</template>。
          <span class="muted">（{{ labels.a }} {{ counts.a_invoices }} 张、{{ labels.b }} {{ counts.b_invoices }} 张有号码）</span>
        </p>
        <table v-if="result.matches?.length" class="grid" aria-label="同号发票">
          <thead>
            <tr><th>发票号码</th><th>判断</th><th>{{ labels.a }}</th><th class="num">价税合计</th><th>{{ labels.b }}</th><th class="num">价税合计</th></tr>
          </thead>
          <tbody>
            <tr v-for="match in result.matches" :key="match.number" :class="{ 'row--failed': match.amount_differs || match.party_differs }">
              <td class="nowrap">
                <button type="button" class="link" @click="focus = { label: match.number, record_ids: match.record_ids, steps: match.steps }">{{ match.number }}</button>
              </td>
              <td class="nowrap">
                <span class="tag" :class="match.kind === 'duplicate' ? 'tag--danger' : ''">{{ match.kind === "duplicate" ? "疑似重复" : "双方同一张票" }}</span>
                <small v-if="match.amount_differs || match.party_differs"> {{ [match.amount_differs ? "金额不同" : "", match.party_differs ? "销售方不同" : ""].filter(Boolean).join("、") }}</small>
              </td>
              <td>{{ match.a.invoice_date || "—" }} · {{ match.a.counterpart || "—" }}</td>
              <td class="num" :class="{ 'check--failed': match.amount_differs }">{{ match.a.total ? money(match.a.total) : "—" }}</td>
              <td>{{ match.b.invoice_date || "—" }} · {{ match.b.counterpart || "—" }}</td>
              <td class="num" :class="{ 'check--failed': match.amount_differs }">{{ match.b.total ? money(match.b.total) : "—" }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">两边没有相同的发票号码。</p>
        <CompareGallery v-if="result.records" :records="result.records" :labels="labels" :focus="focus" @detail="focus = $event" />
        <CompareSources v-if="result.records" :records="result.records" :labels="labels" :focus="focus" @clear="focus = null" @detail="focus = $event" />
        <CompareDrawer v-if="focus" :focus="focus" :labels="labels" @close="focus = null" />
      </template>
    </template>
  </section>
</template>
