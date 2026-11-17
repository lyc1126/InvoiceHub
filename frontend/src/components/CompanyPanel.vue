<script setup lang="ts">
import { ref, watch } from "vue";
import type { Company } from "../api/types";
import CompanyCompare from "./CompanyCompare.vue";
import CompanyDirectories from "./CompanyDirectories.vue";
import CompanyLedger from "./CompanyLedger.vue";
import CompanyPayroll from "./CompanyPayroll.vue";
import CompanyProjects from "./CompanyProjects.vue";
import CompanySettings from "./CompanySettings.vue";
import CompanyVouchers from "./CompanyVouchers.vue";
import CompanyOverview from "./CompanyOverview.vue";
import WorkspaceIcon from "./WorkspaceIcon.vue";

type Tab = "overview" | "directories" | "ledger" | "projects" | "compare" | "vouchers" | "payroll" | "settings";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "总览" },
  { id: "directories", label: "目录" },
  { id: "ledger", label: "发票账簿" },
  { id: "projects", label: "项目" },
  { id: "compare", label: "勾稽" },
  { id: "vouchers", label: "凭证草稿" },
  { id: "payroll", label: "工资社保" },
  { id: "settings", label: "设置" },
];

// One company tab of the workspace home. Each section loads on first open and then stays
// mounted (hidden) so its filters, results and scroll survive switching sections or tabs.
const props = withDefaults(defineProps<{ company: Company; notice?: string; active?: boolean }>(), { active: true });
const tab = ref<Tab>("overview");
const tools = ref<HTMLDetailsElement>();
function selectTab(value: Tab): void { tab.value = value; if (tools.value) tools.value.open = false; }
const opened = ref(new Set<Tab>(["overview", "directories", "settings"]));
watch(tab, (value) => opened.value.add(value));
watch(
  () => props.company.id,
  () => {
    tab.value = "overview";
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
    <details ref="tools" class="company-tools">
    <summary aria-label="公司工具" title="目录、账簿、项目与公司设置"><WorkspaceIcon name="gear" /></summary>
    <div class="tabs company-sections" role="tablist" aria-label="公司内容">
      <button
        v-for="item in TABS"
        :id="`company-tab-${item.id}`"
        :key="item.id"
        type="button"
        role="tab"
        :aria-selected="tab === item.id"
        :aria-controls="`company-panel-${item.id}`"
        @click="selectTab(item.id)"
      >{{ item.label }}</button>
    </div>
    </details>
    <div v-show="tab === 'overview'" id="company-panel-overview" role="tabpanel" aria-labelledby="company-tab-overview">
      <CompanyOverview :company="company" :active="props.active && tab === 'overview'" @section="tab = $event" />
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
      <CompanyCompare :company="company" :active="props.active && tab === 'compare'" />
    </div>
    <div v-if="opened.has('vouchers')" v-show="tab === 'vouchers'" id="company-panel-vouchers" role="tabpanel" aria-labelledby="company-tab-vouchers">
      <CompanyVouchers :company="company" />
    </div>
    <div v-if="opened.has('payroll')" v-show="tab === 'payroll'" id="company-panel-payroll" role="tabpanel" aria-labelledby="company-tab-payroll">
      <CompanyPayroll :company="company" />
    </div>
    <div v-show="tab === 'settings'" id="company-panel-settings" role="tabpanel" aria-labelledby="company-tab-settings">
      <CompanySettings :company="company" />
    </div>
  </section>
</template>
