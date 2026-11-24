<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import AppearanceToggle from "./components/AppearanceToggle.vue";
import WorkspaceIcon from "./components/WorkspaceIcon.vue";
import WorkspaceSidebar from "./components/WorkspaceSidebar.vue";
import WorkspaceModule from "./components/WorkspaceModule.vue";
import HomeView from "./views/HomeView.vue";
import TemporaryRecognitionView from "./views/TemporaryRecognitionView.vue";
import { skinBypassRequested } from "./appearance";
import { MODULES, moduleForPath, workspaceDestination, type ModuleId } from "./modules";
import { useModulesStore } from "./stores/modules";
import { useCompaniesStore } from "./stores/companies";
import { useSystemStore } from "./stores/system";
import { useWorkspaceStore } from "./stores/workspace";
import WsModal from "./components/WsModal.vue";
import ShutdownDialog from "./components/ShutdownDialog.vue";
import CompanyCreateForm from "./components/CompanyCreateForm.vue";
import ServerConnectModal from "./components/ServerConnectModal.vue";
import ServerSourcesPanel from "./components/ServerSourcesPanel.vue";
import FeedbackDialog from "./components/FeedbackDialog.vue";
import { useSourcesStore } from "./stores/sources";
import { toast } from "./toast";
import { toastMessage } from "./toast";

const system = useSystemStore();
const companies = useCompaniesStore();
const workspace = useWorkspaceStore();
const modules = useModulesStore();
const sourcesStore = useSourcesStore();
const route = useRoute();
const router = useRouter();
const recovery = computed(() => skinBypassRequested(route.query.no_skin));
const classicHref = (href: string) => recovery.value ? `${href}?no_skin=1` : href;
// /temporary stays a real route (desktop drag-in targets it), but like the prototype it is a
// dialog over the view that was open before; closing returns to that view's address.
const underlay = ref<{ name: string; path: string }>({ name: "home", path: "/" });
watch(() => route.fullPath, () => { if (route.name !== "temporary") underlay.value = { name: String(route.name ?? "home"), path: route.fullPath }; }, { immediate: true });
const shown = computed(() => route.name === "temporary" ? underlay.value.name : String(route.name ?? "home"));
function closeTemporary(): void { void router.push(underlay.value.path); }
const classic = computed(() => MODULES.some((item) => item.id === shown.value));
const moduleDimmed = computed(() => classic.value && modules.modals[shown.value as ModuleId] === true);
const appearance = ref<InstanceType<typeof AppearanceToggle>>();
const eventError = ref(false);
const sidebarOpen = ref(false);
const feedbackOpen = ref(false);
const feedbackVisited = ref(false);
function openFeedback(): void { feedbackVisited.value = true; feedbackOpen.value = true; }
watch(() => route.query.feedback, (value) => { if (value === "1") openFeedback(); }, { immediate: true });
function closeFeedback(): void {
  feedbackOpen.value = false;
  if (route.query.feedback) { const query = { ...route.query }; delete query.feedback; void router.replace({ query }); }
}
const serverOpen = ref(false);
const serverConnectOpen = ref(false);

async function openServerEntry(): Promise<void> {
  sidebarOpen.value = false;
  const list = sourcesStore.sources.length ? sourcesStore.sources : await sourcesStore.load();
  if (!list.length) {
    serverConnectOpen.value = true;
  } else {
    serverOpen.value = true;
  }
}

function onServerConnected(sourceId: string): void {
  sourcesStore.selectedId = sourceId;
  serverOpen.value = true;
}

function openServerWorkspaceTab(payload: { sourceId: string; parentId: string; sourceName: string; dirName: string }): void {
  workspace.open({
    kind: "server-dir",
    sourceId: payload.sourceId,
    parentId: payload.parentId,
    sourceLabel: payload.sourceName,
    dirLabel: payload.dirName,
  });
  serverOpen.value = false;
  if (route.name !== "home") navigate("/");
}

function openServerPanelFor(sourceId: string): void {
  sourcesStore.selectedId = sourceId;
  serverOpen.value = true;
}
const scroll: Record<string, number> = {};
let previous = "";
let navigation = 0;
let stream: EventSource | undefined;
let eventTimer: ReturnType<typeof setTimeout> | undefined;

watch(() => route.fullPath, async () => {
  const name = String(route.name ?? "home");
  if (previous) scroll[previous] = window.scrollY;
  previous = name;
  modules.visits.add(name);
  const item = MODULES.find((entry) => entry.id === name);
  if (item && (route.hash || Object.keys(route.query).some((key) => key !== "no_skin"))) {
    const url = new URL(item.path, location.origin);
    for (const [key, value] of Object.entries(route.query)) if (typeof value === "string" && key !== "feedback") url.searchParams.set(key, value);
    url.hash = route.hash;
    modules.open(item.id, `${url.pathname}${url.search}${url.hash}`);
  }
  const turn = ++navigation;
  await nextTick();
  if (turn === navigation) window.scrollTo(0, scroll[name] ?? 0);
}, { immediate: true });

function navigate(path: string, force = false): void {
  const destination = workspaceDestination(path);
  if (destination === null) return;
  const url = new URL(destination, location.origin);
  // The authenticated settings frame requests an outer modal; do not replace its document/drafts.
  if (url.pathname === "/settings" && url.searchParams.get("feedback") === "1") { openFeedback(); return; }
  if (recovery.value) url.searchParams.set("no_skin", "1");
  const item = moduleForPath(url.pathname);
  if (item && force) {
    // Batch inbound handoff targets the active monitored directory; make sure the Documents
    // module has that company selected so the embedded classic frame is visible immediately.
    if (item.id === "documents" && url.searchParams.get("batch") === "inbound") {
      const monitored = companies.companies.find((entry) => entry.monitored);
      if (monitored) {
        modules.select("documents", {
          kind: monitored.monitored_subdir_key ? "directory" : "company",
          companyId: monitored.id,
          dirKey: monitored.monitored_subdir_key ?? undefined,
        });
      }
    }
    modules.open(item.id, `${url.pathname}${url.search}${url.hash}`);
    void router.push({ name: item.id, query: recovery.value ? { no_skin: "1" } : {} });
  } else void router.push(`${url.pathname}${url.search}${url.hash}`);
}
function handoff(event: Event): void {
  const detail = (event as CustomEvent).detail;
  if (typeof detail?.path === "string") navigate(detail.path, detail.refresh === true);
}
function syncFrames(): void { window.dispatchEvent(new Event("workspace:appearance-sync")); }
function refreshData(): void {
  clearTimeout(eventTimer);
  eventTimer = setTimeout(() => {
    void system.refresh(); void companies.load();
    window.dispatchEvent(new Event("workspace:invoices-updated"));
  }, 180);
}
onMounted(() => {
  void system.refresh();
  window.addEventListener("workspace:navigate", handoff);
  // One outer stream keeps the home cache and monitor identity current. Hidden
  // classic views pause their own transports, leaving at most two active SSEs.
  if (typeof EventSource === "function") {
    stream = new EventSource("/api/v1/events/stream");
    let opened = false;
    stream.onopen = () => { eventError.value = false; if (opened) refreshData(); opened = true; };
    stream.onerror = () => { eventError.value = true; };
    for (const type of ["settings.watch_dir_updated", "monitor.started", "monitor.stopped", "monitor.sync_completed", "bridge.rebuild_completed", "invoice.changed", "cost_analysis.updated"]) stream.addEventListener(type, refreshData);
    stream.addEventListener("company.data_refreshed", (event) => {
      try {
        const parsed = JSON.parse((event as MessageEvent).data || "{}");
        const companyId = parsed?.payload?.company_id;
        if (typeof companyId === "string" && companyId) {
          window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId } }));
        }
      } catch {
        // Ignore malformed SSE payload; polling already updates state.
      }
    });
  }
});
onBeforeUnmount(() => { ++navigation; stream?.close(); clearTimeout(eventTimer); window.removeEventListener("workspace:navigate", handoff); });

// Double click rebuilds only the active home tab or module context and rereads
// its data. Other cached views and anything already saved remain untouched.
function refreshPage(): void {
  void system.refresh();
  if (route.name === "home") {
    workspace.refreshActive();
    void companies.load();
    scroll.home = 0; window.scrollTo(0, 0);
  } else modules.reload(String(route.name));
}
function focusModalFrame(): void { document.querySelector<HTMLIFrameElement>(".module-frame--modal")?.focus(); }
// Power opens the shell's own confirm in place (prototype); it no longer switches to Settings.
const shutdownOpen = ref(false);
// Registration result goes to a toast (prototype feedback) and the new company opens as a home tab.
// Registering an existing folder also starts a background read-only scan so invoice data is ready to view
// immediately without switching the active monitored directory.
function onCompanyCreated(sources: Record<string, string>): void {
  workspace.createOpen = false;
  const id = companies.selectedId;
  if (!id) return;
  const created = Object.values(sources).filter((value) => value === "created").length;
  const detected = Object.values(sources).filter((value) => value === "detected" || value === "standard").length;
  const isNewWorkspace = created > 0 && detected === 0;
  toast(
    isNewWorkspace
      ? "已新建工作区并登记，六类空目录已创建；当前监控目录保持不变。"
      : `已登记。识别到 ${detected} 个已有子目录，正在后台读取发票数据…`,
    "info",
    4000,
  );
  workspace.open({ kind: "company", companyId: id });
  if (route.name !== "home") navigate("/");
  if (!isNewWorkspace) void companies.refreshData(id, { silent: true });
}
function showShutdown(): void { shutdownOpen.value = true; }
</script>

<template>
  <div class="shell" :class="{ 'shell--module': classic, 'shell--sidebar-open': sidebarOpen }" :style="{ '--ws-sidebar': `${workspace.sidebarWidth}px` }">
    <nav class="rail" aria-label="模块">
      <span class="brand" title="双击：只刷新本页" @dblclick="refreshPage">hi.</span>
      <RouterLink :to="{ path: '/', query: recovery ? { no_skin: '1' } : {} }" class="rail-link"><WorkspaceIcon name="home" />首页</RouterLink>
      <RouterLink :to="{ name: 'temporary', query: recovery ? { no_skin: '1' } : {} }" class="rail-link rail-link--tool" title="识别零散发票，不写入任何公司档案" aria-haspopup="dialog"><WorkspaceIcon name="temp" />临时识别</RouterLink>
      <template v-for="item in MODULES" :key="item.id">
        <span v-if="item.id === 'costs' || item.id === 'settings'" class="rail-sep" aria-hidden="true" />
        <RouterLink class="rail-link" :to="{ name: item.id, query: recovery ? { no_skin: '1' } : {} }">
          <WorkspaceIcon :name="item.icon" />{{ item.label }}
        </RouterLink>
      </template>
      <AppearanceToggle ref="appearance" :recovery="recovery" @changed="syncFrames" />
      <RouterLink class="rail-link rail-link--update" :to="{ name: 'settings', hash: '#about', query: recovery ? { no_skin: '1' } : {} }" title="设置 › 关于与更新" aria-label="关于与更新"><WorkspaceIcon name="up" /></RouterLink>
      <a class="rail-link rail-link--classic" :href="classicHref('/')" title="返回经典界面">经典界面</a>
      <button class="rail-power" type="button" aria-label="关闭系统" title="关闭系统" @click="showShutdown"><WorkspaceIcon name="power" /></button>
    </nav>
    <WorkspaceSidebar @opened="sidebarOpen = false" @server="openServerEntry" @keydown.escape="sidebarOpen = false" />
    <div v-if="sidebarOpen" class="ws-backdrop" aria-hidden="true" @click="sidebarOpen = false" />
    <!-- Matches the active classic dialog's in-frame backdrop; the frame itself sits above it. -->
    <div v-if="classic && moduleDimmed" class="ws-module-scrim" aria-hidden="true" @click="focusModalFrame" />
    <main class="content" :class="{ 'content--home': shown === 'home', 'content--module': classic }">
      <button v-if="shown !== 'home'" class="ws-sidebar-toggle module-sidebar-toggle" type="button" :aria-expanded="sidebarOpen" @click="sidebarOpen = !sidebarOpen"><WorkspaceIcon name="building" />公司与目录</button>
      <p v-if="system.error" class="banner banner--error" role="alert">{{ system.error }}</p>
      <p v-if="eventError" class="banner banner--note" role="status">系统事件连接已断开，正在重连；当前页面保留上次状态。</p>
      <!-- Attached v-show caches preserve browsing contexts as well as Vue state.
           Home tabs belong only to home; other modules never render its tab strip. -->
      <HomeView v-if="modules.visits.has('home')" v-show="shown === 'home'" :active="shown === 'home'" :sidebar-open="sidebarOpen" @toggle-sidebar="sidebarOpen = !sidebarOpen" @open-server-panel="openServerPanelFor" />
      <!-- Kept mounted (v-show inside the dialog host) so the queue and settings draft survive closing. -->
      <WsModal v-if="modules.visits.has('temporary')" :open="route.name === 'temporary'" :escape="false" title="临时识别" subtitle="识别零散发票，结果只在本窗口，不写入任何公司档案。" :wide="true" @close="closeTemporary">
        <TemporaryRecognitionView :active="route.name === 'temporary'" :refresh="modules.refresh.temporary ?? 0" @exit="closeTemporary" />
      </WsModal>
      <template v-for="item in MODULES" :key="item.id">
        <WorkspaceModule v-if="modules.visits.has(item.id)" v-show="shown === item.id" :module="item.id" :path="item.path" :label="item.label" :active="shown === item.id" :recovery="recovery" @navigate="navigate" @appearance="appearance?.syncFromServer()" @state-changed="refreshData" />
      </template>
      <ServerSourcesPanel
        :open="serverOpen"
        @close="serverOpen = false"
        @open-connect="serverConnectOpen = true"
        @open-workspace="openServerWorkspaceTab"
      />
    </main>
    <ShutdownDialog v-if="shutdownOpen" @close="shutdownOpen = false" />
    <FeedbackDialog v-if="feedbackVisited" :open="feedbackOpen" @close="closeFeedback" />
    <ServerConnectModal :open="serverConnectOpen" @close="serverConnectOpen = false" @connected="onServerConnected" />
    <WsModal v-if="workspace.createOpen" title="添加公司资料夹" subtitle="登记已有公司资料夹，或在空位置新建标准工作区。" @close="workspace.createOpen = false">
      <CompanyCreateForm @created="onCompanyCreated" @cancel="workspace.createOpen = false" />
    </WsModal>
    <div v-if="toastMessage" :key="toastMessage.id" class="ws-toast" :class="{ 'ws-toast--error': toastMessage.tone === 'error' }" role="status">{{ toastMessage.text }}</div>
  </div>
</template>
