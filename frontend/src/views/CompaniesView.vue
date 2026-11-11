<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import CompanyCompare from "../components/CompanyCompare.vue";
import CompanyCreateForm from "../components/CompanyCreateForm.vue";
import CompanyDirectories from "../components/CompanyDirectories.vue";
import CompanyLedger from "../components/CompanyLedger.vue";
import CompanyProjects from "../components/CompanyProjects.vue";
import CompanySettings from "../components/CompanySettings.vue";
import { useCompaniesStore } from "../stores/companies";

type Tab = "directories" | "ledger" | "projects" | "compare" | "settings";
const TABS: { id: Tab; label: string }[] = [
  { id: "directories", label: "目录" },
  { id: "ledger", label: "发票账簿" },
  { id: "projects", label: "项目" },
  { id: "compare", label: "勾稽" },
  { id: "settings", label: "设置" },
];

const companies = useCompaniesStore();
const creating = ref(false);
const tab = ref<Tab>("directories");
const createdNotice = ref("");
// The ledger reads two folders and checks their freshness, so it loads on first open and
// then stays mounted (hidden) to keep its filters and result.
const ledgerOpened = ref(false);
const compareOpened = ref(false);
const projectsOpened = ref(false);
watch(tab, (value) => {
  if (value === "ledger") ledgerOpened.value = true;
  if (value === "compare") compareOpened.value = true;
  if (value === "projects") projectsOpened.value = true;
});

function onCreated(sources: Record<string, string>): void {
  creating.value = false;
  tab.value = "directories";
  const detected = Object.values(sources).filter((value) => value === "detected" || value === "standard").length;
  createdNotice.value = `已登记。识别到 ${detected} 个已有子目录，其余可在“目录”里补建。`;
}

function select(id: string): void {
  companies.selectedId = id;
  createdNotice.value = "";
}

onMounted(() => {
  if (!companies.list) void companies.load();
});
</script>

<template>
  <section class="companies">
    <header class="page-header">
      <h1>公司</h1>
      <button type="button" :disabled="companies.loading" :aria-busy="companies.loading" @click="companies.load()">刷新</button>
    </header>
    <p v-if="companies.error" class="banner banner--error" role="alert">{{ companies.error }}</p>

    <div class="split">
      <aside class="company-list" aria-label="公司清单">
        <button type="button" class="primary block" @click="creating = !creating">{{ creating ? "收起" : "新建公司" }}</button>
        <p v-if="companies.list && !companies.companies.length" class="muted">还没有登记公司。</p>
        <ul role="listbox" aria-label="公司">
          <li v-for="item in companies.companies" :key="item.id">
            <button
              type="button"
              role="option"
              class="company-item"
              :aria-selected="item.id === companies.selectedId"
              :title="item.root_path"
              @click="select(item.id)"
            >
              <span class="company-name">{{ item.name }}</span>
              <span class="company-meta">
                <span v-if="item.monitored" class="tag tag--accent">监控中</span>
                <span v-if="item.root_status !== 'present'" class="tag tag--danger">资料夹不可用</span>
                <span v-else-if="item.missing_subdir_count" class="tag">缺 {{ item.missing_subdir_count }} 个子目录</span>
                <span class="muted">{{ item.current_taxpayer_label }}</span>
              </span>
            </button>
          </li>
        </ul>
      </aside>

      <div class="company-detail">
        <CompanyCreateForm v-if="creating" @created="onCreated" @cancel="creating = false" />
        <template v-else-if="companies.selected">
          <header class="detail-header">
            <h2>{{ companies.selected.name }}</h2>
            <p class="muted path">{{ companies.selected.root_path }}</p>
          </header>
          <p v-if="createdNotice" class="banner banner--ok" role="status">{{ createdNotice }}</p>
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
          <!-- v-show keeps each tab's state (filters, scroll, loaded data) while switching. -->
          <div v-show="tab === 'directories'" :id="'company-panel-directories'" role="tabpanel" aria-labelledby="company-tab-directories">
            <CompanyDirectories :company="companies.selected" />
          </div>
          <div v-if="tab === 'ledger' || ledgerOpened" v-show="tab === 'ledger'" :id="'company-panel-ledger'" role="tabpanel" aria-labelledby="company-tab-ledger">
            <CompanyLedger :company="companies.selected" />
          </div>
          <div v-if="tab === 'projects' || projectsOpened" v-show="tab === 'projects'" :id="'company-panel-projects'" role="tabpanel" aria-labelledby="company-tab-projects">
            <CompanyProjects :company="companies.selected" />
          </div>
          <div v-if="tab === 'compare' || compareOpened" v-show="tab === 'compare'" :id="'company-panel-compare'" role="tabpanel" aria-labelledby="company-tab-compare">
            <CompanyCompare :company="companies.selected" />
          </div>
          <div v-show="tab === 'settings'" :id="'company-panel-settings'" role="tabpanel" aria-labelledby="company-tab-settings">
            <CompanySettings :company="companies.selected" />
          </div>
        </template>
        <p v-else-if="companies.list" class="muted">在左侧选择一家公司，或新建公司。</p>
      </div>
    </div>
  </section>
</template>
