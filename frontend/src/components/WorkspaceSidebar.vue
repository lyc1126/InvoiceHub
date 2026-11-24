<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import WorkspaceIcon from "./WorkspaceIcon.vue";
import WsModal from "./WsModal.vue";
import ProjectRenameModal from "./ProjectRenameModal.vue";
import { MODULES, type ModuleId } from "../modules";
import { useModulesStore } from "../stores/modules";
import { skinBypassRequested } from "../appearance";
import { ApiError, request } from "../api/client";
import type { Company, CompanySubdir, ProjectRenameResult, ProjectSummary, SubdirPlan } from "../api/types";
import { errorText } from "../format";
import { INVOICE_DIRS, SAME_NUMBER, relationFor } from "../relations";
import { companySourceKey, useCompaniesStore } from "../stores/companies";
import { useSystemStore } from "../stores/system";
import { SIDEBAR_DEFAULT, clampSidebar, useWorkspaceStore } from "../stores/workspace";
import { toast } from "../toast";

// Workspace sidebar (WS-01): 置顶 and 公司 › 项目 / 目录. Clicking a node opens it as a home tab;
// right click, the row's ⋯ button or Shift+F10 opens the same menu (pin, pick for a comparison).
// Opening a directory never changes the monitored folder; that stays an explicit action.
const emit = defineEmits<{ opened: []; server: [] }>();
const companies = useCompaniesStore();
const system = useSystemStore();
const workspace = useWorkspaceStore();
const route = useRoute();
const router = useRouter();
const modules = useModulesStore();
const searchOpen = ref(false);
const search = ref("");
const visibleCompanies = computed(() => companies.companies.filter(company => {
  const term = search.value.trim().toLocaleLowerCase();
  return !term || [company.name, company.root_path, ...company.subdirs.map(dir => dir.label), ...(projects.value[company.id]?.names ?? [])].some(value => value.toLocaleLowerCase().includes(term));
}));
function nodeIcon(node: SidebarNode): string {
  return node.kind === "company" ? "building" : node.kind === "project" ? "project" : node.dirKey === "bank_flow_dir" ? "bank" : "folder";
}
function isCurrent(companyId: string, kind: SidebarNode["kind"], dirKey?: string): boolean {
  const current = route.name !== "settings" && MODULES.some(item => item.id === route.name)
    ? modules.selections[route.name as ModuleId] : workspace.active;
  return current?.companyId === companyId && current.kind === kind && (kind !== "directory" || current.dirKey === dirKey);
}
function openHome(spec: Parameters<typeof workspace.open>[0]): void {
  workspace.open(spec);
  if (route.name !== "home") void router.push({ name: "home", query: route.query });
  emit("opened");
}
const classicHref = computed(() => skinBypassRequested(route.query.no_skin) ? "/?no_skin=1" : "/");

const KIND_TAGS: Record<string, string> = {
  cost_invoice_dir: "进项",
  issued_invoice_dir: "销项",
  bank_flow_dir: "流水",
  input_deduction_dir: "抵扣",
  payroll_social_dir: "工资",
  expense_reimbursement_dir: "报销",
};

interface SidebarNode {
  id: string;
  kind: "company" | "directory" | "project";
  company: Company;
  dirKey?: string;
  project?: string;
  label: string;
  sub: string;
  path: string;
  subdir?: CompanySubdir;
}

// Project names per company, read when the company is first expanded (the summary reads two
// projections, so it is not fetched for collapsed companies).
const projects = ref<Record<string, { names: string[]; error: string; loading: boolean; sourceKey: string }>>({});

function companyNode(company: Company): SidebarNode {
  const present = company.subdirs.filter((item) => item.status === "present").length;
  return {
    id: `company:${company.id}`, kind: "company", company, label: company.name,
    sub: `${company.current_taxpayer_label} · 资料 ${present}/${company.subdirs.length}`, path: company.root_path,
  };
}

function directoryNode(company: Company, subdir: CompanySubdir): SidebarNode {
  return {
    id: `dir:${company.id}:${subdir.key}`, kind: "directory", company, dirKey: subdir.key, subdir,
    label: subdir.label, sub: company.name, path: subdir.path,
  };
}

function projectNode(company: Company, name: string): SidebarNode {
  return { id: `project:${company.id}:${name}`, kind: "project", company, project: name, label: name, sub: company.name, path: company.root_path };
}

const nodesById = computed(() => {
  const map = new Map<string, SidebarNode>();
  for (const company of companies.companies) {
    const node = companyNode(company);
    map.set(node.id, node);
    for (const subdir of company.subdirs) {
      const child = directoryNode(company, subdir);
      map.set(child.id, child);
    }
    for (const name of projects.value[company.id]?.names ?? []) {
      const child = projectNode(company, name);
      map.set(child.id, child);
    }
  }
  return map;
});

// A pin whose company was removed simply disappears; project pins survive until projects load.
const pinned = computed(() =>
  workspace.pins.map((id) => nodesById.value.get(id) ?? pinnedProject(id)).filter((node): node is SidebarNode => !!node),
);

function pinnedProject(id: string): SidebarNode | null {
  const [kind, companyId, ...rest] = id.split(":");
  const company = companies.companies.find((item) => item.id === companyId);
  return kind === "project" && company ? projectNode(company, rest.join(":")) : null;
}

const watchLabel = computed(() => {
  const company = companies.companies.find((item) => item.monitored);
  const subdir = company?.subdirs.find((item) => item.key === company.monitored_subdir_key);
  if (company && subdir) return `${company.name} · ${subdir.label}`;
  return system.settings?.watch_dir || "";
});

async function loadProjects(company: Company): Promise<void> {
  if (company.root_status !== "present") return;
  const sourceKey = companySourceKey(company, ["cost_invoice_dir", "issued_invoice_dir"]);
  projects.value[company.id] = { names: [], error: "", loading: true, sourceKey };
  try {
    const summary = await request<ProjectSummary>(`/api/v1/companies/${encodeURIComponent(company.id)}/projects?granularity=year`);
    if (projects.value[company.id]?.sourceKey !== sourceKey) return;
    projects.value[company.id] = { sourceKey, names: summary.projects.filter((row) => !row.unassigned).map((row) => row.project), error: "", loading: false };
  } catch (cause) {
    if (projects.value[company.id]?.sourceKey === sourceKey) projects.value[company.id] = { sourceKey, names: [], error: errorText(cause), loading: false };
  }
}

function toggle(company: Company): void {
  workspace.toggleExpanded(company.id);
  if (workspace.expanded.includes(company.id) && !projects.value[company.id]) void loadProjects(company);
}

// Companies remembered as expanded load their projects once the list is known.
watch(
  () => companies.companies,
  (list) => {
    for (const company of list) {
      const cached = projects.value[company.id];
      if (cached && cached.sourceKey !== companySourceKey(company, ["cost_invoice_dir", "issued_invoice_dir"])) delete projects.value[company.id];
      if (workspace.expanded.includes(company.id) && !projects.value[company.id]) void loadProjects(company);
    }
  },
  { immediate: true },
);

function open(node: SidebarNode): void {
  closeMenu(false);
  const spec = { kind: node.kind, companyId: node.company.id, dirKey: node.dirKey, project: node.project };
  if (MODULES.some(item => item.id === route.name) && route.name !== "settings") {
    // Module selections are independent UI contexts. They never change watch_dir;
    // consumers must check whether their existing API can serve the selected company.
    modules.select(route.name as ModuleId, spec);
  } else openHome(spec);
  emit("opened");
}

// ---- comparison: pick one folder, then compare another folder with it. A related pair of one
// company is reconciled; two invoice folders otherwise (also across companies) only get the
// same-number check; anything else is refused with the reason.
function compareState(node: SidebarNode): { ok: boolean; reason: string; relation?: string } {
  const base = workspace.compareBase;
  if (!base || node.kind !== "directory") return { ok: false, reason: "" };
  const sameCompany = base.companyId === node.company.id;
  if (sameCompany && base.dirKey === node.dirKey) return { ok: false, reason: "这是已选的目录" };
  const relation = sameCompany ? relationFor(base.dirKey, node.dirKey ?? "") : null;
  if (relation) return { ok: true, reason: relation.label, relation: relation.id };
  if (INVOICE_DIRS.includes(base.dirKey) && INVOICE_DIRS.includes(node.dirKey ?? "")) {
    return { ok: true, reason: "检查两个目录是否有相同发票号", relation: SAME_NUMBER };
  }
  return { ok: false, reason: sameCompany ? "这两类资料不能直接配对核对" : "不同公司之间只能核对发票目录的相同票号" };
}

function pickForCompare(node: SidebarNode): void {
  workspace.compareBase = node.dirKey ? { companyId: node.company.id, dirKey: node.dirKey } : null;
  closeMenu();
}

function compareWith(node: SidebarNode): void {
  const state = compareState(node);
  const base = workspace.compareBase;
  if (!state.ok || !base) return;
  if (state.relation === SAME_NUMBER) {
    openHome({ kind: "compare", companyId: base.companyId, dirKey: base.dirKey, relation: SAME_NUMBER,
      otherCompanyId: node.company.id, otherDirKey: node.dirKey });
  } else {
    openHome({ kind: "compare", companyId: node.company.id, relation: state.relation });
  }
  workspace.compareBase = null;
  closeMenu(false);
  emit("opened");
}

function isBase(node: SidebarNode): boolean {
  return node.kind === "directory" && workspace.compareBase?.companyId === node.company.id && workspace.compareBase.dirKey === node.dirKey;
}

// ---- context menu
const menu = ref<{ node: SidebarNode; x: number; y: number; origin: HTMLElement | null } | null>(null);
const menuEl = ref<HTMLElement | null>(null);

// ---- single missing subfolder creation (preview -> confirm -> mkdir only)
const createModal = ref<{ companyId: string; companyName: string; dirKey: string; label: string; plan: SubdirPlan | null; loading: boolean; busy: boolean; error: string } | null>(null);

async function startCreateSubdir(node: SidebarNode): Promise<void> {
  if (node.kind !== "directory" || !node.dirKey) return;
  closeMenu(false);
  const state = { companyId: node.company.id, companyName: node.company.name, dirKey: node.dirKey, label: node.label, plan: null as SubdirPlan | null, loading: true, busy: false, error: "" };
  createModal.value = state;
  try {
    const plan = await companies.subdirPlan(node.company.id, [node.dirKey]);
    if (createModal.value === state) createModal.value = { ...state, plan, loading: false };
  } catch (cause) {
    if (createModal.value === state) createModal.value = { ...state, loading: false, error: errorText(cause) };
  }
}

async function confirmCreateSubdir(): Promise<void> {
  const current = createModal.value;
  if (!current?.plan || current.busy) return;
  current.busy = true;
  current.error = "";
  try {
    const result = await companies.createSubdirs(current.companyId, current.plan.plan_hash, [current.dirKey]);
    if (result.failed.length) {
      current.error = result.failed.map((item) => item.message).join("；");
      current.busy = false;
      return;
    }
    createModal.value = null;
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: current.companyId } }));
    toast(`已创建空文件夹「${current.label}」`, "info", 3000);
  } catch (cause) {
    current.error = cause instanceof ApiError && cause.code === "COMPANY_PLAN_STALE" ? "目录状态已变化，请关闭后重新打开预览。" : errorText(cause);
    current.busy = false;
  }
}

function openMenu(node: SidebarNode, event: MouseEvent | KeyboardEvent): void {
  const origin = (event.currentTarget as HTMLElement | null) ?? null;
  const box = origin?.getBoundingClientRect();
  const fromPointer = event instanceof MouseEvent && event.clientX;
  const x = fromPointer ? (event as MouseEvent).clientX : (box?.right ?? 0) - 8;
  const y = fromPointer ? (event as MouseEvent).clientY : (box?.bottom ?? 0);
  menu.value = { node, x: Math.min(x, window.innerWidth - 220), y: Math.min(y, window.innerHeight - 200), origin };
  void nextTick(() => menuEl.value?.querySelector<HTMLElement>("button:not(:disabled)")?.focus());
}

function closeMenu(restoreFocus = true): void {
  const origin = menu.value?.origin;
  menu.value = null;
  if (restoreFocus) origin?.focus();
}

function onRowKey(node: SidebarNode, event: KeyboardEvent): void {
  if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
    event.preventDefault();
    openMenu(node, event);
  }
}

function onMenuKey(event: KeyboardEvent): void {
  const items = [...(menuEl.value?.querySelectorAll<HTMLElement>("button:not(:disabled)") ?? [])];
  const index = items.indexOf(document.activeElement as HTMLElement);
  if (event.key === "Escape") closeMenu();
  else if (event.key === "ArrowDown") items[(index + 1) % items.length]?.focus();
  else if (event.key === "ArrowUp") items[(index - 1 + items.length) % items.length]?.focus();
  else return;
  event.preventDefault();
}

function onDocumentPointer(event: PointerEvent): void {
  if (menu.value && !menuEl.value?.contains(event.target as Node)) closeMenu(false);
}
document.addEventListener("pointerdown", onDocumentPointer);

// ---- hover card with the full name and path (long names are cut with an ellipsis)
const card = ref<{ node: SidebarNode; top: number; left: number } | null>(null);
let cardTimer: ReturnType<typeof setTimeout> | undefined;

function showCard(node: SidebarNode, event: Event): void {
  clearTimeout(cardTimer);
  const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
  cardTimer = setTimeout(() => {
    card.value = { node, top: box.top, left: box.right + 8 };
  }, 450);
}

function hideCard(): void {
  clearTimeout(cardTimer);
  card.value = null;
}

// ---- resize: 220—460 px, the content keeps at least 620 px; double click resets.
const limitHint = ref("");
const RAIL = 72;

function setWidth(width: number): void {
  const next = clampSidebar(width, window.innerWidth, RAIL);
  workspace.sidebarWidth = next.width;
  limitHint.value = next.limited === "min" ? "已到最小宽度" : next.limited === "max" ? "已到最大宽度" : "";
}

function startResize(event: PointerEvent): void {
  const handle = event.currentTarget as HTMLElement;
  handle.setPointerCapture(event.pointerId);
  const startX = event.clientX;
  const startWidth = workspace.sidebarWidth;
  const move = (next: PointerEvent) => setWidth(startWidth + next.clientX - startX);
  const stop = () => {
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", stop);
    handle.removeEventListener("pointercancel", stop);
    setTimeout(() => (limitHint.value = ""), 900);
  };
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", stop);
  handle.addEventListener("pointercancel", stop);
}

function onResizeKey(event: KeyboardEvent): void {
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    setWidth(workspace.sidebarWidth + (event.key === "ArrowRight" ? 16 : -16));
  } else if (event.key === "Home") {
    setWidth(SIDEBAR_DEFAULT);
  }
}

const headerMenu = ref(false);
const renameModal = ref<{
  company: Company;
  fromName: string;
  revision: number;
  projectNames: string[];
} | null>(null);

async function startRenameProject(node: SidebarNode): Promise<void> {
  if (!node.project) return;
  closeMenu(false);
  try {
    const summary = await request<ProjectSummary>(`/api/v1/companies/${encodeURIComponent(node.company.id)}/projects?granularity=year`);
    renameModal.value = {
      company: node.company,
      fromName: node.project,
      revision: summary.assignments_revision,
      projectNames: summary.project_names,
    };
  } catch (cause) {
    toast(errorText(cause), "error", 4000);
  }
}

function onSidebarProjectRenamed(result: ProjectRenameResult): void {
  const activeModal = renameModal.value;
  renameModal.value = null;
  if (!activeModal) return;
  const company = activeModal.company;
  // Keep open project tabs and pins synchronized with the renamed project name.
  const oldTabId = `project:${company.id}:${result.from_name}`;
  const newTabId = `project:${company.id}:${result.to_name}`;
  const existingNew = workspace.tabs.find((tab) => tab.id === newTabId);
  for (const tab of workspace.tabs) {
    if (tab.id === oldTabId) {
      if (existingNew) {
        workspace.close(oldTabId);
        workspace.activeId = newTabId;
      } else {
        tab.id = newTabId;
        tab.project = result.to_name;
        if (workspace.activeId === oldTabId) workspace.activeId = newTabId;
      }
      break;
    }
  }
  if (workspace.pins.includes(oldTabId)) {
    workspace.pins = workspace.pins
      .map((pin) => (pin === oldTabId ? newTabId : pin))
      .filter((pin, idx, list) => list.indexOf(pin) === idx);
  }
  void loadProjects(company);
  toast(`已将项目「${result.from_name}」重命名为「${result.to_name}」`, "info", 3500);
  window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: company.id } }));
}

function onWorkspaceCompanyRefreshed(event: Event): void {
  const detail = (event as CustomEvent).detail;
  for (const company of companies.companies) {
    if (detail?.companyId && detail.companyId !== company.id) continue;
    if (workspace.expanded.includes(company.id)) void loadProjects(company);
  }
}
window.addEventListener("workspace:company-refreshed", onWorkspaceCompanyRefreshed);

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocumentPointer);
  window.removeEventListener("workspace:company-refreshed", onWorkspaceCompanyRefreshed);
  clearTimeout(cardTimer);
});
</script>

<template>
  <aside class="ws-sidebar" aria-label="工作区">
    <div class="ws-sidebar__head">
      <button type="button" class="ws-brand" :aria-expanded="headerMenu" aria-haspopup="menu" @click="headerMenu = !headerMenu">InvoiceHub <WorkspaceIcon name="chev" /></button>
      <button type="button" class="ws-head-button" aria-label="通知与状态" title="查看当前系统状态" @click="headerMenu = !headerMenu"><WorkspaceIcon name="bell" /></button>
      <button type="button" class="ws-head-button" aria-label="搜索公司、项目或目录" :aria-expanded="searchOpen" @click="searchOpen = !searchOpen; search = ''"><WorkspaceIcon name="search" /></button>
      <div v-if="headerMenu" class="ws-menu ws-menu--head" role="menu" @keydown.escape="headerMenu = false">
        <button type="button" role="menuitem" @click="headerMenu = false; companies.load()">刷新公司清单</button>
        <button type="button" role="menuitem" @click="headerMenu = false; openHome({ kind: 'tags' })">发票标签</button>
        <a role="menuitem" :href="classicHref">返回经典界面</a>
      </div>
    </div>
    <label v-if="searchOpen" class="ws-search"><WorkspaceIcon name="search" /><input v-model="search" aria-label="搜索公司、项目或目录" placeholder="搜索公司、项目或目录"></label>
    <button type="button" class="ws-add" aria-haspopup="dialog" @click="workspace.createOpen = true; emit('opened')"><WorkspaceIcon name="building" />添加公司资料夹</button>
    <button type="button" class="ws-add" @click="emit('server')"><svg class="hub-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M12 15v4m-6 2h12M4 18h3m10 0h3" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>服务器链接（试验版）</button>
    <p v-if="workspace.compareBase" class="ws-compare-hint" role="status">
      已选 {{ nodesById.get(`dir:${workspace.compareBase.companyId}:${workspace.compareBase.dirKey}`)?.label ?? "目录" }} 进行核对，请到另一个目录点“与已选项进行比较”（关联资料核对账目，其他发票目录检查重复票号）。
      <button type="button" class="link" @click="workspace.compareBase = null">取消</button>
    </p>

    <nav class="ws-tree" aria-label="公司与目录">
      <h3 class="ws-section">置顶</h3>
      <p v-if="!pinned.length" class="ws-empty-pin">右键任意公司 / 项目 / 目录 →「置顶」</p>
      <template v-else>
        <ul>
          <li v-for="node in pinned" :key="`pin:${node.id}`" class="ws-row ws-row--pin" :class="{ 'ws-row--base': isBase(node) }">
            <button
              type="button"
              class="ws-node"
              :aria-label="`${node.label}（${node.sub}）`"
              @click="open(node)"
              @contextmenu.prevent="openMenu(node, $event)"
              @keydown="onRowKey(node, $event)"
              @mouseenter="showCard(node, $event)"
              @mouseleave="hideCard"
              @focus="hideCard"
            >
              <WorkspaceIcon :name="nodeIcon(node)" />
              <span class="ws-text"><span class="ws-label">{{ node.label }}</span><span class="ws-sub">{{ node.sub }}</span></span>
            </button>
            <button type="button" class="ws-more" :aria-label="`${node.label} 的操作`" @click="openMenu(node, $event)">⋯</button>
          </li>
        </ul>
      </template>

      <h3 class="ws-section">公司 <span class="muted">{{ companies.companies.length }}</span></h3>
      <p v-if="companies.error" class="banner banner--error" role="alert">{{ companies.error }}</p>
      <p v-else-if="companies.list && !companies.companies.length" class="muted ws-empty">还没有登记公司。</p>
      <ul>
        <li v-for="company in visibleCompanies" :key="company.id">
          <div class="ws-row ws-row--company">
            <button
              type="button"
              class="ws-toggle"
              :aria-expanded="workspace.expanded.includes(company.id)"
              :aria-label="`展开 ${company.name}`"
              @click="toggle(company)"
            ><WorkspaceIcon name="chev" /></button>
            <button
              type="button"
              class="ws-node"
              :aria-label="`${company.name}（${companyNode(company).sub}）`"
              :aria-current="isCurrent(company.id, 'company') ? 'page' : undefined"
              @click="open(companyNode(company))"
              @contextmenu.prevent="openMenu(companyNode(company), $event)"
              @keydown="onRowKey(companyNode(company), $event)"
              @mouseenter="showCard(companyNode(company), $event)"
              @mouseleave="hideCard"
              @focus="hideCard"
            >
              <WorkspaceIcon name="building" />
              <span class="ws-text">
                <span class="ws-label">{{ company.name }}</span>
                <span class="ws-sub">{{ companyNode(company).sub }}<template v-if="company.root_status !== 'present'"> · 资料夹不可用</template></span>
              </span>
            </button>
            <button type="button" class="ws-more" :aria-label="`${company.name} 的操作`" @click="openMenu(companyNode(company), $event)">⋯</button>
          </div>
          <ul v-if="workspace.expanded.includes(company.id)" class="ws-children">
            <li v-if="projects[company.id]?.loading" class="muted ws-empty">读取项目…</li>
            <li v-else-if="projects[company.id]?.error" class="muted ws-empty" :title="projects[company.id]?.error">项目读取失败</li>
            <li v-for="name in projects[company.id]?.names ?? []" :key="`p:${name}`" class="ws-row">
              <button
                type="button"
                class="ws-node"
                :aria-label="`项目 ${name}`"
                @click="open(projectNode(company, name))"
                @contextmenu.prevent="openMenu(projectNode(company, name), $event)"
                @keydown="onRowKey(projectNode(company, name), $event)"
                @mouseenter="showCard(projectNode(company, name), $event)"
                @mouseleave="hideCard"
                @focus="hideCard"
              >
                <WorkspaceIcon name="project" />
                <span class="ws-text"><span class="ws-label">{{ name }}</span></span>
              </button>
              <button type="button" class="ws-more" :aria-label="`项目 ${name} 的操作`" @click="openMenu(projectNode(company, name), $event)">⋯</button>
            </li>
            <li
              v-for="subdir in company.subdirs"
              :key="subdir.key"
              class="ws-row"
              :class="{ 'ws-row--missing': subdir.status !== 'present', 'ws-row--base': isBase(directoryNode(company, subdir)) }"
            >
              <button
                type="button"
                class="ws-node"
                :aria-label="`${subdir.label}${subdir.status !== 'present' ? '（缺失）' : ''}${company.monitored_subdir_key === subdir.key ? '（当前监控目录）' : ''}`"
                :aria-current="isCurrent(company.id, 'directory', subdir.key) ? 'page' : undefined"
                @click="open(directoryNode(company, subdir))"
                @contextmenu.prevent="openMenu(directoryNode(company, subdir), $event)"
                @keydown="onRowKey(directoryNode(company, subdir), $event)"
                @mouseenter="showCard(directoryNode(company, subdir), $event)"
                @mouseleave="hideCard"
                @focus="hideCard"
              >
                <WorkspaceIcon :name="subdir.key === 'bank_flow_dir' ? 'bank' : 'folder'" />
                <span class="ws-text"><span class="ws-label">{{ subdir.label }}</span></span>
                <span v-if="company.monitored_subdir_key === subdir.key" class="ws-live" title="当前监控目录" />
                <span class="ws-kind">{{ subdir.status === "present" ? KIND_TAGS[subdir.key] ?? "" : "缺失" }}</span>
              </button>
              <button
                v-if="compareState(directoryNode(company, subdir)).ok"
                type="button"
                class="ws-compare"
                :title="compareState(directoryNode(company, subdir)).reason"
                @click="compareWith(directoryNode(company, subdir))"
              >⇄ 比较</button>
              <button type="button" class="ws-more" :aria-label="`${subdir.label} 的操作`" @click="openMenu(directoryNode(company, subdir), $event)">⋯</button>
            </li>
          </ul>
        </li>
      </ul>
    </nav>

    <p class="ws-status" :title="system.settings?.watch_dir || ''">
      <span class="ws-live" :class="{ 'ws-live--off': !watchLabel }" aria-hidden="true" />
      <span class="ws-status__text">{{ watchLabel ? `当前监控目录（仅 1 个）：${watchLabel}` : "未设置监控目录" }}</span>
    </p>

    <div
      class="ws-resize"
      role="separator"
      tabindex="0"
      aria-orientation="vertical"
      aria-label="调整侧栏宽度（左右方向键，Home 复位）"
      :aria-valuenow="workspace.sidebarWidth"
      aria-valuemin="220"
      aria-valuemax="460"
      @pointerdown="startResize"
      @dblclick="setWidth(SIDEBAR_DEFAULT)"
      @keydown="onResizeKey"
    >
      <span v-if="limitHint" class="ws-resize__hint" role="status">{{ limitHint }}</span>
    </div>

    <div v-if="card" class="ws-card" role="tooltip" :style="{ top: `${card.top}px`, left: `${card.left}px` }">
      <strong>{{ card.node.label }}</strong>
      <span v-if="card.node.sub" class="muted">{{ card.node.sub }}</span>
      <span class="path">{{ card.node.path }}</span>
    </div>

    <div
      v-if="menu"
      ref="menuEl"
      class="ws-menu"
      role="menu"
      :aria-label="`${menu.node.label} 的操作`"
      :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
      @keydown="onMenuKey"
    >
      <button type="button" role="menuitem" @click="open(menu.node)">在标签中打开</button>
      <button type="button" role="menuitem" @click="workspace.togglePin(menu.node.id); closeMenu()">
        {{ workspace.pins.includes(menu.node.id) ? "取消置顶" : "置顶" }}
      </button>
      <button
        v-if="menu.node.kind === 'project'"
        type="button"
        role="menuitem"
        @click="startRenameProject(menu.node)"
      >重命名项目…</button>
      <template v-if="menu.node.kind === 'directory'">
        <button
          v-if="menu.node.subdir?.status === 'missing'"
          type="button"
          role="menuitem"
          @click="startCreateSubdir(menu.node)"
        >创建此文件夹…</button>
        <button
          v-if="!isBase(menu.node)"
          type="button"
          role="menuitem"
          :disabled="menu.node.subdir?.status !== 'present'"
          @click="pickForCompare(menu.node)"
        >选择以进行比较</button>
        <button v-else type="button" role="menuitem" @click="workspace.compareBase = null; closeMenu()">取消比较选择</button>
        <button
          v-if="workspace.compareBase && !isBase(menu.node)"
          type="button"
          role="menuitem"
          :disabled="!compareState(menu.node).ok"
          :title="compareState(menu.node).reason"
          @click="compareWith(menu.node)"
        >与已选项进行比较</button>
        <p v-if="workspace.compareBase && !isBase(menu.node) && !compareState(menu.node).ok" class="muted ws-menu__note">{{ compareState(menu.node).reason }}</p>
      </template>
    </div>

    <WsModal
      v-if="createModal"
      :title="`创建缺失文件夹 · ${createModal.label}`"
      :subtitle="`${createModal.companyName} · 只新建空文件夹，不会移动、删除或改写任何已有文件。`"
      @close="!createModal.busy && (createModal = null)"
    >
      <p v-if="createModal.loading" class="muted" aria-busy="true">正在核对目录路径…</p>
      <p v-if="createModal.error" class="banner banner--error" role="alert">{{ createModal.error }}</p>
      <template v-if="createModal.plan">
        <div class="overview-table-wrap"><table class="grid">
          <thead><tr><th>类型</th><th>子目录路径</th><th>处理</th></tr></thead>
          <tbody>
            <tr v-for="item in createModal.plan.items" :key="item.key" :class="{ 'row--danger': item.action === 'blocked' }">
              <td>{{ item.label }}</td>
              <td class="path mono">{{ item.relative_path }}</td>
              <td>{{ { create: "新建空文件夹", exists: "已存在，跳过", blocked: "无法创建" }[item.action] }}<span v-if="item.reason" class="muted">：{{ item.reason }}</span></td>
            </tr>
          </tbody>
        </table></div>
        <div class="actions">
          <button type="button" class="primary" :disabled="createModal.busy || !createModal.plan.create_count" :aria-busy="createModal.busy" @click="confirmCreateSubdir">{{ createModal.busy ? "创建中…" : "确认创建" }}</button>
          <button type="button" class="ghost" :disabled="createModal.busy" @click="createModal = null">取消</button>
        </div>
      </template>
    </WsModal>

    <ProjectRenameModal
      v-if="renameModal"
      :company-id="renameModal.company.id"
      :company-name="renameModal.company.name"
      :from-name="renameModal.fromName"
      :revision="renameModal.revision"
      :project-names="renameModal.projectNames"
      @close="renameModal = null"
      @done="onSidebarProjectRenamed"
    />
  </aside>
</template>
