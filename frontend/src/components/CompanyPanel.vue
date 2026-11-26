<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { Company } from "../api/types";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { toast } from "../toast";
import CompanyCompare from "./CompanyCompare.vue";
import CompanyDeleteModal from "./CompanyDeleteModal.vue";
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
  { id: "compare", label: "账目核对" },
  { id: "vouchers", label: "凭证草稿" },
  { id: "payroll", label: "工资社保" },
  { id: "settings", label: "设置" },
];

// One company tab of the workspace home. Each section loads on first open and then stays
// mounted (hidden) so its filters, results and scroll survive switching sections or tabs.
const props = withDefaults(defineProps<{ company: Company; notice?: string; active?: boolean }>(), { active: true });
const companies = useCompaniesStore();
const tab = ref<Tab>("overview");
const history = ref<Tab[]>([]);
const tools = ref<HTMLDetailsElement>();
const deleteModalOpen = ref(false);
const currentTabLabel = computed(() => TABS.find((item) => item.id === tab.value)?.label ?? "");
const canGoBack = computed(() => history.value.length > 0 || tab.value !== "overview");
function selectTab(value: Tab): void {
  if (value !== tab.value) {
    history.value.push(tab.value);
    if (history.value.length > 20) history.value.shift();
    tab.value = value;
  }
  if (tools.value) tools.value.open = false;
}
function goBack(): void {
  const previous = history.value.pop();
  tab.value = previous ?? "overview";
  if (tools.value) tools.value.open = false;
}
async function openRootFolder(): Promise<void> {
  try {
    await companies.openCompanyRoot(props.company.id);
  } catch (cause) {
    toast(errorText(cause), "error", 4000);
  }
}
function onOpenSectionEvent(event: Event): void {
  const detail = (event as CustomEvent).detail;
  if (!detail || detail.companyId !== props.company.id) return;
  const target = detail.section as Tab;
  if (TABS.some((item) => item.id === target)) selectTab(target);
}
onMounted(() => window.addEventListener("workspace:open-company-section", onOpenSectionEvent));
onBeforeUnmount(() => window.removeEventListener("workspace:open-company-section", onOpenSectionEvent));
const opened = ref(new Set<Tab>(["overview", "directories", "settings"]));
watch(tab, (value) => opened.value.add(value));
watch(
  () => props.company.id,
  () => {
    tab.value = "overview";
    history.value = [];
    deleteModalOpen.value = false;
  },
);
</script>

<template>
  <section class="company-detail" :aria-label="company.name">
    <header class="detail-header detail-header--split">
      <div>
        <div class="detail-header__title-row">
          <button v-if="canGoBack" type="button" class="company-back" aria-label="返回上一页" title="返回上一页" @click="goBack">
            <svg class="hub-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
          </button>
          <div class="detail-header__heading">
            <p v-if="tab !== 'overview'" class="crumb">{{ company.name }} › {{ currentTabLabel }}</p>
            <h2>{{ company.name }} <span class="tag">{{ company.current_taxpayer_label }}</span></h2>
          </div>
        </div>
        <p class="muted path">{{ company.root_path }}</p>
      </div>
      <div class="company-head-actions">
        <button v-if="company.root_status === 'present'" type="button" class="ghost" @click="openRootFolder">打开文件夹</button>
        <button type="button" class="ghost" @click="selectTab('settings')">公司设置</button>
        <button type="button" class="ghost danger" @click="deleteModalOpen = true">移除 / 删除</button>
      </div>
    </header>
    <p v-if="company.root_status !== 'present'" class="overview-notice overview-notice--warn" role="status">
      <span>当前公司资料夹在硬盘上不可用，请到公司设置重新定位文件夹路径，或从清单移除。</span>
      <button type="button" @click="selectTab('settings')">重定位目录</button>
    </p>
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
      <CompanyOverview :company="company" :active="props.active && tab === 'overview'" @section="selectTab($event)" />
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
    <CompanyDeleteModal
      v-if="deleteModalOpen"
      :company="company"
      @close="deleteModalOpen = false"
      @done="deleteModalOpen = false"
    />
  </section>
</template>

<style scoped>
.company-head-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
</style>
