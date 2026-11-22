<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { request } from "../api/client";
import { costBase, today, warningText, type CostSnapshot } from "../api/costV2";
import type { Company } from "../api/types";
import { errorText } from "../format";
import { companySourceKey } from "../stores/companies";
import CostAnalysis from "./CostAnalysis.vue";
import CostInventorySetup from "./CostInventorySetup.vue";
import CostItems from "./CostItems.vue";
import CostQuote from "./CostQuote.vue";
import CostRecords from "./CostRecords.vue";
import CostRules from "./CostRules.vue";
import CostServiceCosts from "./CostServiceCosts.vue";

type Tab = "quote" | "items" | "rules" | "analysis" | "monitor" | "inventory" | "records" | "service";
const TABS: { id: Tab; label: string }[] = [
  { id: "quote", label: "定价助手" },
  { id: "items", label: "品目与迁移" },
  { id: "rules", label: "定价规则" },
  { id: "analysis", label: "毛利分析" },
  { id: "monitor", label: "价格监控" },
  { id: "inventory", label: "库存对照" },
  { id: "records", label: "报价记录" },
  { id: "service", label: "服务成本" },
];

// Company cost V2 workbench. It reads the company's last complete cost/issued projections
// through the V2 API, so unlike the classic /costs frame it works for any registered company
// without switching the active monitor directory. Quote, item and rule tabs share one
// snapshot (revision + rules_revision); every write tab rereads it after a confirmed save.
const props = withDefaults(defineProps<{ company: Company; active?: boolean }>(), { active: true });
const tab = ref<Tab>("quote");
const opened = ref(new Set<Tab>(["quote"]));
const pricingDate = ref(today());
const snapshot = ref<CostSnapshot | null>(null);
const loading = ref(false);
const error = ref("");
const base = computed(() => costBase(props.company.id));
// Records and analysis keep their own reads; bumping this after a save tells them to reload.
const saved = ref(0);
let generation = 0;
let disposed = false;

function select(value: Tab): void { tab.value = value; opened.value.add(value); }

async function load(): Promise<void> {
  const mine = ++generation;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(pricingDate.value)) { error.value = "计划开票日期须为 YYYY-MM-DD。"; return; }
  loading.value = true;
  try {
    const result = await request<CostSnapshot>(`${base.value}?pricing_date=${pricingDate.value}`, { timeoutMs: 120_000 });
    if (disposed || mine !== generation) return;
    snapshot.value = result;
    error.value = "";
  } catch (cause) {
    if (disposed || mine !== generation) return;
    error.value = errorText(cause);
    // A failed read for another planning date (e.g. before the confirmed stock opening)
    // must not leave the previous date's prices under the new date.
    if (snapshot.value && snapshot.value.pricing_date !== pricingDate.value) snapshot.value = null;
  } finally { if (mine === generation) loading.value = false; }
}

function changed(): void { saved.value += 1; void load(); }

watch(pricingDate, () => { void load(); });
watch(() => companySourceKey(props.company, ["cost_invoice_dir", "issued_invoice_dir"]), () => {
  // Never keep another company's prices, rules or drafts visible while the new one loads.
  generation += 1;
  snapshot.value = null;
  error.value = "";
  void load();
}, { immediate: true });
onBeforeUnmount(() => { disposed = true; generation += 1; });

const sourceNotes = computed(() => Object.entries(snapshot.value?.sources ?? {})
  .filter(([, source]) => source.freshness && !["fresh", "monitored"].includes(source.freshness.state))
  .map(([side, source]) => `${side === "input" ? "成本发票" : "开具发票"}：${source.freshness?.message || source.freshness?.state}`));
</script>

<template>
  <section class="panel cost-v2" :aria-label="`${company.name} 成本分析 V2`">
    <header class="voucher__head cost-v2__head">
      <h3>成本分析 V2</h3>
      <label class="field">计划开票日<input v-model.lazy="pricingDate" type="date" aria-label="计划开票日" :disabled="loading"></label>
      <button type="button" :disabled="loading" :aria-busy="loading" @click="load">{{ loading ? "读取中…" : "重新读取" }}</button>
    </header>
    <p class="overview-notice">报价与分析读取本公司进销发票的上次完整汇总；品目归类须预览确认，会同步更新品目表与兼容工作簿。成本按品类月末一次加权，规格不分摊成本。</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <template v-if="snapshot">
      <p v-if="!snapshot.complete" class="banner banner--note" role="status">来源投影不完整或已过期：结存成本显示为未知，报价会标“待核对”，不回退历史均价。</p>
      <ul v-if="sourceNotes.length || snapshot.warnings.length" class="warnings"><li v-for="note in [...sourceNotes, ...snapshot.warnings.map(warningText)]" :key="note">{{ note }}</li></ul>
    </template>
    <div class="tabs" role="tablist" aria-label="成本分析 V2 内容">
      <button v-for="item in TABS" :id="`cost-v2-tab-${item.id}`" :key="item.id" type="button" role="tab" :aria-selected="tab === item.id" @click="select(item.id)">{{ item.label }}</button>
    </div>
    <div v-show="tab === 'quote'" role="tabpanel" aria-labelledby="cost-v2-tab-quote">
      <CostQuote :company="company" :snapshot="snapshot" :busy="loading" @changed="changed" @reload="load" />
    </div>
    <div v-if="opened.has('items')" v-show="tab === 'items'" role="tabpanel" aria-labelledby="cost-v2-tab-items">
      <CostItems :company="company" :snapshot="snapshot" :busy="loading" @changed="changed" @reload="load" />
    </div>
    <div v-if="opened.has('rules')" v-show="tab === 'rules'" role="tabpanel" aria-labelledby="cost-v2-tab-rules">
      <CostRules :company="company" :snapshot="snapshot" :busy="loading" @changed="changed" @reload="load" />
    </div>
    <div v-if="opened.has('analysis')" v-show="tab === 'analysis'" role="tabpanel" aria-labelledby="cost-v2-tab-analysis">
      <CostAnalysis :company="company" mode="analysis" :saved="saved" />
    </div>
    <div v-if="opened.has('monitor')" v-show="tab === 'monitor'" role="tabpanel" aria-labelledby="cost-v2-tab-monitor">
      <CostAnalysis :company="company" mode="monitor" :saved="saved" :items="snapshot?.items ?? []" />
    </div>
    <div v-if="opened.has('inventory')" v-show="tab === 'inventory'" role="tabpanel" aria-labelledby="cost-v2-tab-inventory">
      <CostInventorySetup :company="company" :snapshot="snapshot" :saved="saved" @changed="changed" />
    </div>
    <div v-if="opened.has('records')" v-show="tab === 'records'" role="tabpanel" aria-labelledby="cost-v2-tab-records">
      <CostRecords :company="company" :saved="saved" />
    </div>
    <div v-if="opened.has('service')" v-show="tab === 'service'" role="tabpanel" aria-labelledby="cost-v2-tab-service">
      <CostServiceCosts :company="company" :saved="saved" @changed="changed" />
    </div>
  </section>
</template>

<style scoped>
/* Eight tabs must wrap as whole labels on narrow windows, never one character per line. */
.cost-v2 :deep(.tabs) { flex-wrap: wrap; }
.cost-v2 :deep(.tabs [role="tab"]) { white-space: nowrap; }
</style>
