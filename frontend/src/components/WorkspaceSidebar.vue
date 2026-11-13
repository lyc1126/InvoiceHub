<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { request } from "../api/client";
import type { Company, CompanySubdir, ProjectSummary } from "../api/types";
import { errorText } from "../format";
import { INVOICE_DIRS, SAME_NUMBER, relationFor } from "../relations";
import { useCompaniesStore } from "../stores/companies";
import { useSystemStore } from "../stores/system";
import { SIDEBAR_DEFAULT, clampSidebar, useWorkspaceStore } from "../stores/workspace";

// Workspace sidebar (WS-01): 置顶 and 公司 › 项目 / 目录. Clicking a node opens it as a home tab;
// right click, the row's ⋯ button or Shift+F10 opens the same menu (pin, pick for a comparison).
// Opening a directory never changes the monitored folder; that stays an explicit action.
const emit = defineEmits<{ opened: [] }>();
const companies = useCompaniesStore();
const system = useSystemStore();
const workspace = useWorkspaceStore();

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
const projects = ref<Record<string, { names: string[]; error: string; loading: boolean }>>({});

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
  projects.value[company.id] = { names: projects.value[company.id]?.names ?? [], error: "", loading: true };
  try {
    const summary = await request<ProjectSummary>(`/api/v1/companies/${encodeURIComponent(company.id)}/projects?granularity=year`);
    projects.value[company.id] = { names: summary.projects.filter((row) => !row.unassigned).map((row) => row.project), error: "", loading: false };
  } catch (cause) {
    projects.value[company.id] = { names: [], error: errorText(cause), loading: false };
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
      if (workspace.expanded.includes(company.id) && !projects.value[company.id]) void loadProjects(company);
    }
  },
  { immediate: true },
);

function open(node: SidebarNode): void {
  closeMenu(false);
  if (node.kind === "company") workspace.open({ kind: "company", companyId: node.company.id });
  else if (node.kind === "directory") workspace.open({ kind: "directory", companyId: node.company.id, dirKey: node.dirKey });
  else workspace.open({ kind: "project", companyId: node.company.id, project: node.project });
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
    return { ok: true, reason: "同号发票检查（不做勾稽关联）", relation: SAME_NUMBER };
  }
  return { ok: false, reason: sameCompany ? "这两类资料之间没有勾稽关系" : "不同公司之间只能对发票目录做同号检查" };
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
    workspace.open({ kind: "compare", companyId: base.companyId, dirKey: base.dirKey, relation: SAME_NUMBER,
      otherCompanyId: node.company.id, otherDirKey: node.dirKey });
  } else {
    workspace.open({ kind: "compare", companyId: node.company.id, relation: state.relation });
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

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocumentPointer);
  clearTimeout(cardTimer);
});
</script>

<template>
  <aside class="ws-sidebar" aria-label="工作区">
    <div class="ws-sidebar__head">
      <button type="button" class="ws-brand" :aria-expanded="headerMenu" aria-haspopup="menu" @click="headerMenu = !headerMenu">InvoiceHub ⌄</button>
      <div v-if="headerMenu" class="ws-menu ws-menu--head" role="menu" @keydown.escape="headerMenu = false">
        <button type="button" role="menuitem" @click="headerMenu = false; companies.load()">刷新公司清单</button>
        <button type="button" role="menuitem" @click="headerMenu = false; workspace.open({ kind: 'tags' }); emit('opened')">发票标签</button>
        <a role="menuitem" href="/">返回经典界面</a>
      </div>
    </div>
    <button type="button" class="ws-add" @click="workspace.open({ kind: 'new-company' }); emit('opened')">＋ 添加公司资料夹</button>
    <p v-if="workspace.compareBase" class="ws-compare-hint" role="status">
      已选择 {{ nodesById.get(`dir:${workspace.compareBase.companyId}:${workspace.compareBase.dirKey}`)?.label ?? "目录" }} 进行比较：在另一个目录上选“与已选项进行比较”：同一公司有勾稽关系的做核对，发票目录之间做同号检查。
      <button type="button" class="link" @click="workspace.compareBase = null">取消</button>
    </p>

    <nav class="ws-tree" aria-label="公司与目录">
      <template v-if="pinned.length">
        <h3 class="ws-section">置顶</h3>
        <ul>
          <li v-for="node in pinned" :key="`pin:${node.id}`" class="ws-row" :class="{ 'ws-row--base': isBase(node) }">
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
              <span class="ws-icon" aria-hidden="true">{{ node.kind === "company" ? "▦" : node.kind === "project" ? "◇" : "▭" }}</span>
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
        <li v-for="company in companies.companies" :key="company.id">
          <div class="ws-row ws-row--company">
            <button
              type="button"
              class="ws-toggle"
              :aria-expanded="workspace.expanded.includes(company.id)"
              :aria-label="`展开 ${company.name}`"
              @click="toggle(company)"
            >{{ workspace.expanded.includes(company.id) ? "▾" : "▸" }}</button>
            <button
              type="button"
              class="ws-node"
              :aria-label="`${company.name}（${companyNode(company).sub}）`"
              :aria-current="workspace.active?.kind === 'company' && workspace.active.companyId === company.id ? 'page' : undefined"
              @click="open(companyNode(company))"
              @contextmenu.prevent="openMenu(companyNode(company), $event)"
              @keydown="onRowKey(companyNode(company), $event)"
              @mouseenter="showCard(companyNode(company), $event)"
              @mouseleave="hideCard"
              @focus="hideCard"
            >
              <span class="ws-icon" aria-hidden="true">▦</span>
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
                <span class="ws-icon" aria-hidden="true">◇</span>
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
                :aria-label="`${subdir.label}${subdir.status !== 'present' ? '（缺失）' : ''}${company.monitored_subdir_key === subdir.key ? '（监控中）' : ''}`"
                :aria-current="workspace.active?.kind === 'directory' && workspace.active.companyId === company.id && workspace.active.dirKey === subdir.key ? 'page' : undefined"
                @click="open(directoryNode(company, subdir))"
                @contextmenu.prevent="openMenu(directoryNode(company, subdir), $event)"
                @keydown="onRowKey(directoryNode(company, subdir), $event)"
                @mouseenter="showCard(directoryNode(company, subdir), $event)"
                @mouseleave="hideCard"
                @focus="hideCard"
              >
                <span class="ws-icon" aria-hidden="true">▭</span>
                <span class="ws-text"><span class="ws-label">{{ subdir.label }}</span></span>
                <span v-if="company.monitored_subdir_key === subdir.key" class="ws-live" title="监控中" />
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
      <span class="ws-status__text">{{ watchLabel ? `实时监控中（仅 1 个目录）：${watchLabel}` : "未设置监控目录" }}</span>
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
      <template v-if="menu.node.kind === 'directory'">
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
  </aside>
</template>
