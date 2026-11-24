<script setup lang="ts">
import { computed, onMounted, provide, ref, watch } from "vue";
import { VIEW_ACTIVE } from "../modules";
import CompanyCompare from "../components/CompanyCompare.vue";
import CompanyPanel from "../components/CompanyPanel.vue";
import CompanyProjects from "../components/CompanyProjects.vue";
import CompanySameNumber from "../components/CompanySameNumber.vue";
import DirectoryPanel from "../components/DirectoryPanel.vue";
import InvoiceTagsEditor from "../components/InvoiceTagsEditor.vue";
import ServerDirectoryPanel from "../components/ServerDirectoryPanel.vue";
import WorkspaceIcon from "../components/WorkspaceIcon.vue";
import { RELATIONS, SAME_NUMBER } from "../relations";
import { useCompaniesStore } from "../stores/companies";
import { useSourcesStore } from "../stores/sources";
import { useSystemStore } from "../stores/system";
import { type WorkspaceTab, tabId, useWorkspaceStore } from "../stores/workspace";

// Workspace home (WS-01): sidebar + tabs. Every open tab stays mounted (v-show) so its
// filters, results and scroll survive switching; closing a tab drops that cache. The tab's
// `refresh` counter is part of its key, so "hi." rebuilds only the active one.
const companies = useCompaniesStore();
const sources = useSourcesStore();
const props = withDefaults(defineProps<{ active?: boolean; sidebarOpen?: boolean }>(), { active: true, sidebarOpen: false });
const emit = defineEmits<{ toggleSidebar: []; openServerPanel: [sourceId: string] }>();
provide(VIEW_ACTIVE, computed(() => props.active));
const system = useSystemStore();
const workspace = useWorkspaceStore();

const companyOf = (tab: WorkspaceTab) => companies.companies.find((item) => item.id === tab.companyId) ?? null;
const otherCompanyOf = (tab: WorkspaceTab) => companies.companies.find((item) => item.id === tab.otherCompanyId) ?? null;
const dirLabel = (company: { subdirs: { key: string; label: string }[] }, key?: string) => company.subdirs.find((item) => item.key === key)?.label ?? key ?? "";

function title(tab: WorkspaceTab): string {
  if (tab.kind === "server-dir") {
    const srcName = sources.byId(tab.sourceId ?? "")?.name || tab.sourceLabel || "服务器";
    const sub = tab.dirLabel && tab.dirLabel !== srcName ? ` · ${tab.dirLabel}` : "";
    return `${srcName}${sub}`;
  }
  const company = companyOf(tab);
  if (tab.kind === "new-company") return "添加公司资料夹";
  if (tab.kind === "tags") return "发票标签";
  if (!company) return "（已删除）";
  if (tab.kind === "directory") return `${company.name} · ${company.subdirs.find((item) => item.key === tab.dirKey)?.label ?? tab.dirKey}`;
  if (tab.kind === "project") return `${company.name} · ${tab.project}`;
  if (tab.kind === "compare" && tab.relation === SAME_NUMBER) {
    const other = otherCompanyOf(tab);
    if (!other) return "（已删除）";
    const right = other.id === company.id ? dirLabel(other, tab.otherDirKey) : `${other.name} · ${dirLabel(other, tab.otherDirKey)}`;
    return `${company.name} · ${dirLabel(company, tab.dirKey)} ⇄ ${right}`;
  }
  if (tab.kind === "compare") {
    const relation = RELATIONS.find((item) => item.id === tab.relation);
    return `${company.name} · ${relation ? relation.label.split("（")[0] : "勾稽"}`;
  }
  return company.name;
}

// Stable DOM ids per tab (indexes shift when a tab closes).
const domId = (tab: WorkspaceTab) => tab.id.replace(/[^A-Za-z0-9_-]/g, (char) => `_${char.codePointAt(0)!.toString(36)}`);

const ICONS: Record<WorkspaceTab["kind"], string> = { company: "building", directory: "folder", project: "project", compare: "compare", "new-company": "plus", tags: "pick", "server-dir": "server" };


function onTabKey(event: KeyboardEvent, index: number): void {
  const tabs = workspace.tabs;
  let next = -1;
  if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
  else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
  else if (event.key === "Delete") {
    workspace.close(tabs[index]!.id);
    return;
  } else return;
  event.preventDefault();
  workspace.activeId = tabs[next]!.id;
  document.getElementById(`ws-tab-${domId(tabs[next]!)}`)?.focus();
}

// A tab whose company or server source was deleted closes itself instead of showing stale data.
watch(
  () => companies.list,
  (list) => {
    if (!list) return;
    for (const tab of [...workspace.tabs]) {
      if ((tab.companyId && !companyOf(tab)) || (tab.otherCompanyId && !otherCompanyOf(tab))) workspace.close(tab.id);
    }
    // First visit: open the monitored company once (closing every tab later leaves the start page).
    if (!workspace.seeded) {
      const first = list.monitored_company_id ?? list.companies[0]?.id;
      if (first) workspace.open({ kind: "company", companyId: first });
      workspace.seeded = true;
    }
  },
  { immediate: true },
);

watch(
  () => sources.sources,
  (list) => {
    if (!list.length && sources.loading) return;
    for (const tab of [...workspace.tabs]) {
      if (tab.kind === "server-dir" && tab.sourceId && !sources.byId(tab.sourceId) && !sources.loading) {
        workspace.close(tab.id);
      }
    }
  },
);

const monitoredCompany = computed(() => companies.companies.find((item) => item.monitored) ?? null);

onMounted(() => {
  if (!companies.list) void companies.load();
});
</script>

<template>
  <div class="ws-home">
    <div class="ws-main">
      <div class="ws-tabbar">
        <button type="button" class="ws-sidebar-toggle" :aria-expanded="sidebarOpen" @click="$emit('toggleSidebar')"><WorkspaceIcon name="building" />公司与目录</button>
        <div class="ws-tabs" role="tablist" aria-label="已打开">
          <div
            v-for="(tab, index) in workspace.tabs"
            :key="tab.id"
            class="ws-tab"
            :class="{ 'ws-tab--active': tab.id === workspace.activeId }"
            @auxclick.middle="workspace.close(tab.id)"
          >
            <button
              :id="`ws-tab-${domId(tab)}`"
              type="button"
              role="tab"
              :aria-selected="tab.id === workspace.activeId"
              :aria-controls="`ws-panel-${domId(tab)}`"
              :tabindex="tab.id === workspace.activeId ? 0 : -1"
              :title="title(tab)"
              @click="workspace.activeId = tab.id"
              @keydown="onTabKey($event, index)"
            >
              <WorkspaceIcon :name="ICONS[tab.kind]" />
              <span class="ws-tab__title">{{ title(tab) }}</span>
            </button>
            <button type="button" class="ws-tab__close" :aria-label="`关闭 ${title(tab)}`" @click="workspace.close(tab.id)"><WorkspaceIcon name="x" /></button>
          </div>
        </div>
      </div>

      <div class="ws-content">
        <template v-for="tab in workspace.tabs" :key="`${tab.id}#${tab.refresh}`">
          <div v-show="tab.id === workspace.activeId" :id="`ws-panel-${domId(tab)}`" role="tabpanel" :aria-labelledby="`ws-tab-${domId(tab)}`">
            <InvoiceTagsEditor v-if="tab.kind === 'tags'" />
            <ServerDirectoryPanel
              v-else-if="tab.kind === 'server-dir' && tab.sourceId"
              :source-id="tab.sourceId"
              :parent-id="tab.parentId ?? ''"
              :active="tab.id === workspace.activeId"
              @open-panel="emit('openServerPanel', $event)"
            />
            <template v-else-if="companyOf(tab)">
              <CompanyPanel v-if="tab.kind === 'company'" :company="companyOf(tab)!" :active="tab.id === workspace.activeId" />
              <DirectoryPanel v-else-if="tab.kind === 'directory'" :company="companyOf(tab)!" :dir-key="tab.dirKey!" />
              <section v-else-if="tab.kind === 'project'" :aria-label="title(tab)">
                <header class="detail-header"><h2>{{ title(tab) }}</h2><p class="muted">项目取自发票备注的“项目名称”，没有的可在下方人工指定。</p></header>
                <CompanyProjects :company="companyOf(tab)!" :focus="tab.project" />
              </section>
              <section v-else-if="tab.kind === 'compare' && tab.relation === SAME_NUMBER" :aria-label="title(tab)">
                <header class="detail-header"><h2>⇄ 同号检查：{{ title(tab) }}</h2><p class="muted">核对这两个目录里有没有相同或重复的发票号码；只读，不会修改任何文件。</p></header>
                <CompanySameNumber v-if="otherCompanyOf(tab)" :company="companyOf(tab)!" :dir-key="tab.dirKey!" :other-company="otherCompanyOf(tab)!" :other-dir-key="tab.otherDirKey!" :active="tab.id === workspace.activeId" />
                <p v-else class="muted">另一家公司已删除。</p>
              </section>
              <section v-else-if="tab.kind === 'compare'" :aria-label="title(tab)">
                <header class="detail-header"><h2>⇄ {{ title(tab) }}</h2><p class="muted">核对同一家公司的两类资料是否对得上；只读，不会修改任何文件。</p></header>
                <CompanyCompare :company="companyOf(tab)!" :relation="tab.relation" :active="tab.id === workspace.activeId" />
              </section>
            </template>
          </div>
        </template>

        <section v-if="!workspace.tabs.length" class="ws-start" aria-label="起始页">
          <span class="brand start-brand" aria-hidden="true">hi.</span>
          <h1>今天处理哪家公司？</h1>
          <p class="muted">从左侧选择公司、项目或目录，会在上方打开标签；关掉所有标签就回到这里。</p>
          <div class="actions">
            <button v-if="monitoredCompany" type="button" class="primary" @click="workspace.open({ kind: 'company', companyId: monitoredCompany.id })">
              打开 {{ monitoredCompany.name }}
            </button>
            <button type="button" aria-haspopup="dialog" @click="workspace.createOpen = true">添加公司资料夹</button>
            <button type="button" @click="$router.push({ name: 'temporary', query: $route.query })"><WorkspaceIcon name="temp" />临时识别</button>
          </div>
          <table v-if="system.health" class="facts">
            <tbody>
              <tr><th scope="row">版本</th><td>{{ system.health.product_version || "—" }}</td></tr>
              <tr><th scope="row">后台状态</th><td>{{ system.health.background_status || "—" }}</td></tr>
              <tr><th scope="row">当前监控目录</th><td>{{ system.health.watch_dir || "—" }}</td></tr>
            </tbody>
          </table>
        </section>
      </div>
    </div>
  </div>
</template>
