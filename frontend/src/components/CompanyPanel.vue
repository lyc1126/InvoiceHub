<script setup lang="ts">
import { ref, watch } from "vue";
import type { Company } from "../api/types";
import CompanyCompare from "./CompanyCompare.vue";
import CompanyDirectories from "./CompanyDirectories.vue";
import CompanyLedger from "./CompanyLedger.vue";
import CompanyProjects from "./CompanyProjects.vue";
import CompanySettings from "./CompanySettings.vue";
import CompanyVouchers from "./CompanyVouchers.vue";

type Tab = "directories" | "ledger" | "projects" | "compare" | "vouchers" | "settings";
const TABS: { id: Tab; label: string }[] = [
  { id: "directories", label: "目录" },
  { id: "ledger", label: "发票账簿" },
  { id: "projects", label: "项目" },
  { id: "compare", label: "勾稽" },
  { id: "vouchers", label: "凭证草稿" },
  { id: "settings", label: "设置" },
];

// One company tab of the workspace home. Each section loads on first open and then stays
// mounted (hidden) so its filters, results and scroll survive switching sections or tabs.
const props = defineProps<{ company: Company; notice?: string }>();
const tab = ref<Tab>("directories");
const opened = ref(new Set<Tab>(["directories", "settings"]));
watch(tab, (value) => opened.value.add(value));
watch(
  () => props.company.id,
  () => {
    tab.value = "directories";
  },
);
</script>

<template>
  <section class="company-detail" :aria-label="company.name">
    <header class="detail-header">
      <h2>{{ company.name }} <span class="tag">{{ company.current_taxpayer_label }}</span></h2>
      <p class="muted path">{{ company.root_path }}</p>
    </header>
    <p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <div class="tabs" role="tablist" aria-label="公司内容">
      <button
        v-for="item in TABS"
        :id="`company-tab-${item.id}`"
        :key="item.id"
        type="button"
        role="tab"
        :aria-selected="tab === item.id"
        :aria-controls="`company-panel-${item.id}`"
        @click="tab = item.id"
      >{{ item.label }}</button>
    </div>
    <div v-show="tab === 'directories'" id="company-panel-directories" role="tabpanel" aria-labelledby="company-tab-directories">
      <CompanyDirectories :company="company" />
    </div>
    <div v-if="opened.has('ledger')" v-show="tab === 'ledger'" id="company-panel-ledger" role="tabpanel" aria-labelledby="company-tab-ledger">
      <CompanyLedger :company="company" />
    </div>
    <div v-if="opened.has('projects')" v-show="tab === 'projects'" id="company-panel-projects" role="tabpanel" aria-labelledby="company-tab-projects">
      <CompanyProjects :company="company" />
    </div>
    <div v-if="opened.has('compare')" v-show="tab === 'compare'" id="company-panel-compare" role="tabpanel" aria-labelledby="company-tab-compare">
      <CompanyCompare :company="company" />
    </div>
    <div v-if="opened.has('vouchers')" v-show="tab === 'vouchers'" id="company-panel-vouchers" role="tabpanel" aria-labelledby="company-tab-vouchers">
      <CompanyVouchers :company="company" />
    </div>
    <div v-show="tab === 'settings'" id="company-panel-settings" role="tabpanel" aria-labelledby="company-tab-settings">
      <CompanySettings :company="company" />
    </div>
  </section>
</template>
