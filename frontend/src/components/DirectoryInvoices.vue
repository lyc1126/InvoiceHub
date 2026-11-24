<script setup lang="ts">
import { companySourceKey } from "../stores/companies";
import { computed, inject, nextTick, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { VIEW_ACTIVE } from "../modules";
import { ApiError, request } from "../api/client";
import type { Company, DirectoryInvoicesPayload, InvoiceRow, InvoiceTagMarks, PreviewRef, ProjectSummary } from "../api/types";
import { errorText, ratePercent, money } from "../format";
import { useTagsStore } from "../stores/tags";
import { useWorkspaceStore, type InvoiceColumnKey } from "../stores/workspace";
import { toast } from "../toast";
import SourcePreview from "./SourcePreview.vue";
import DirectorySelectionBar, { type SelectedInvoice, type TrashJob } from "./DirectorySelectionBar.vue";
import WorkspaceIcon from "./WorkspaceIcon.vue";
import WsModal from "./WsModal.vue";

// One company folder's invoice list (last projection; read-only unless it is the monitored
// folder). Shown in a directory tab of the workspace home; tags are display data only.
const props = defineProps<{ company: Company; dirKey: string }>();
const tagStore = useTagsStore();
const workspace = useWorkspaceStore();
const viewActive = inject(VIEW_ACTIVE, ref(true));
let stale = false;
function refreshFromEvent(): void {
  if (viewActive.value) void loadInvoices(invoicesPage.value);
  else stale = true;
}
function onCompanyRefreshed(event: Event): void {
  const detail = (event as CustomEvent).detail;
  if (!detail?.companyId || detail.companyId === props.company.id) refreshFromEvent();
}
watch(viewActive, (active) => {
  if (!active) {
    columnMenuOpen.value = false;
    tagMenu.value = null;
    return;
  }
  if (stale) { stale = false; void loadInvoices(invoicesPage.value); }
});
const tagFilter = ref("");
// Prototype filters; all are applied by the server before sorting/paging (WEB_UI rule).
const keyword = ref("");
const fileExt = ref("");
const statusFilter = ref("");
let keywordTimer: ReturnType<typeof setTimeout> | undefined;
function keywordChanged(): void { clearTimeout(keywordTimer); keywordTimer = setTimeout(() => void loadInvoices(1), 300); }
// Revision of this company's 发票标签.json, read lazily before the first mark is saved.
const marksRevision = ref<number | null>(null);
// Batch mode (WS-06): opened on a row that belongs to a multi-row selection, the menu works on
// every selected invoice number. Their current marks are read when the menu opens, because the
// selection may span pages the list never loaded.
interface BatchTags { numbers: string[]; missing: number; revision: number | null; invoices: Record<string, string[]> | null }
const tagMenu = ref<{ row: InvoiceRow; x: number; y: number; origin: HTMLElement; batch: BatchTags | null } | null>(null);
const tagMenuEl = ref<HTMLElement | null>(null);
const tagBusy = ref(false);
const error = ref("");
const invoices = ref<DirectoryInvoicesPayload | null>(null);
const invoicesPage = ref(1);
const invoicesLoading = ref(false);
const PAGE_SIZE = 50;
const dateSort = ref<"" | "asc" | "desc">("");
const previewing = ref<PreviewRef | null>(null);
let listGeneration = 0;
let selectionGeneration = 0;
const dateSortLabel = computed(() => dateSort.value === "asc" ? "按开票时间倒序排序" : "按开票时间正序排序");
const formatLabel = (row: InvoiceRow) => ["PDF", "OFD", "XML"].includes(row.file_format?.toUpperCase()) ? row.file_format.toUpperCase() : "未知";
const formatTone = (row: InvoiceRow) => formatLabel(row) === "未知" ? "unknown" : formatLabel(row).toLowerCase();
// Settled nonmonitor lists can select for company tags. Source actions retain a separate
// active-target gate: selecting a remote/local historical row never authorizes file operations.
type SelectedRow = SelectedInvoice & { invoice_number: string };
const selected = ref(new Map<string, SelectedRow>());
const selectingAll = ref(false);
const selectable = computed(() => !!invoices.value && !invoices.value.snapshot?.provisional);
const sourceActions = computed(() => selectable.value && !invoices.value?.read_only);
const isProjectDir = computed(() => props.dirKey === "cost_invoice_dir" || props.dirKey === "issued_invoice_dir");

// Column visibility (UI preference in workspace store, keyed by dirKey so hiding 购买方 in
// 成本发票 does not hide it in 开具发票). Structural tag-dot and checkbox columns stay fixed.
const ALL_INVOICE_COLUMNS: readonly { key: InvoiceColumnKey; label: string; projectOnly?: boolean }[] = [
  { key: "seller", label: "销售方" },
  { key: "buyer", label: "购买方" },
  { key: "format", label: "格式" },
  { key: "invoice_number", label: "发票号码" },
  { key: "project", label: "项目", projectOnly: true },
  { key: "classification", label: "发票分类与业务" },
  { key: "tax_rate", label: "税率" },
  { key: "amount", label: "开票金额" },
  { key: "invoice_date", label: "开票时间" },
  { key: "status", label: "状态" },
];
const columnMenuId = `invoice-columns-${Math.random().toString(36).slice(2, 9)}`;
const columnMenuOpen = ref(false);
const columnMenuPos = ref({ left: "8px", top: "8px" });
const columnMenuWrap = ref<HTMLElement | null>(null);
const columnMenuTrigger = ref<HTMLButtonElement | null>(null);
const columnMenuEl = ref<HTMLElement | null>(null);
const availableColumns = computed(() => ALL_INVOICE_COLUMNS.filter((col) => !col.projectOnly || isProjectDir.value));
const availableColumnKeys = computed(() => availableColumns.value.map((col) => col.key));
const hiddenColumns = computed(() => workspace.hiddenColumnsFor(props.dirKey, availableColumnKeys.value));
const hiddenColumnSet = computed(() => new Set<InvoiceColumnKey>(hiddenColumns.value));
const visibleColumnCount = computed(() => availableColumns.value.length - hiddenColumns.value.length);
const isColumnVisible = (key: InvoiceColumnKey): boolean => !hiddenColumnSet.value.has(key);

function positionColumnMenu(anchor?: { x: number; y: number }): void {
  void nextTick(() => {
    const el = columnMenuEl.value;
    if (!el || !columnMenuOpen.value) return;
    const menuBox = el.getBoundingClientRect();
    const width = menuBox.width || 220;
    const height = menuBox.height || 300;
    let left: number;
    let top: number;
    if (anchor) {
      left = anchor.x;
      top = anchor.y;
    } else {
      const triggerBox = columnMenuTrigger.value?.getBoundingClientRect();
      left = triggerBox ? triggerBox.right - width : 8;
      top = triggerBox ? triggerBox.bottom + 6 : 8;
      if (triggerBox && top + height > window.innerHeight - 8 && triggerBox.top - height - 6 >= 8) {
        top = triggerBox.top - height - 6;
      }
    }
    columnMenuPos.value = {
      left: `${Math.max(8, Math.min(left, window.innerWidth - width - 8))}px`,
      top: `${Math.max(8, Math.min(top, window.innerHeight - height - 8))}px`,
    };
    el.querySelector<HTMLElement>("input:not(:disabled), button:not(:disabled)")?.focus();
  });
}

function toggleColumnMenu(): void {
  if (columnMenuOpen.value) {
    columnMenuOpen.value = false;
    return;
  }
  tagMenu.value = null;
  columnMenuOpen.value = true;
  positionColumnMenu();
}

function openColumnMenuAtHeader(event: MouseEvent): void {
  tagMenu.value = null;
  columnMenuOpen.value = true;
  positionColumnMenu(event.clientX ? { x: event.clientX, y: event.clientY } : undefined);
}

function closeColumnMenu(restoreFocus = false): void {
  if (!columnMenuOpen.value) return;
  columnMenuOpen.value = false;
  if (restoreFocus) columnMenuTrigger.value?.focus();
}

function onToggleColumn(key: InvoiceColumnKey): void {
  workspace.toggleInvoiceColumn(props.dirKey, key, availableColumnKeys.value);
}

function resetColumns(): void {
  workspace.resetInvoiceColumns(props.dirKey);
}

function onDocumentPointerDown(event: Event): void {
  if (!columnMenuOpen.value) return;
  const target = event.target as Node | null;
  if (target && (columnMenuWrap.value?.contains(target) || columnMenuEl.value?.contains(target))) return;
  columnMenuOpen.value = false;
}

function onDocumentKeyDown(event: KeyboardEvent): void {
  // Hidden KeepAlive tabs must not intercept window Escape (WEB_UI rule).
  if (!viewActive.value || !columnMenuOpen.value || event.key !== "Escape") return;
  event.preventDefault();
  event.stopPropagation();
  closeColumnMenu(true);
}
const selectedItems = computed(() => [...selected.value.values()].map(({ invoice_key, source_path }) => ({ invoice_key, source_path })));
const entry = (row: InvoiceRow): SelectedRow => ({ invoice_key: row.invoice_key, source_path: row.source_path!, invoice_number: row.invoice_number ?? "" });
const pageRows = computed(() => (invoices.value?.items ?? []).filter((row) => row.source_path));
const pageState = computed(() => {
  const count = pageRows.value.filter((row) => selected.value.has(row.invoice_key)).length;
  return { all: count > 0 && count === pageRows.value.length, some: count > 0 && count < pageRows.value.length };
});

function toggleRow(row: InvoiceRow): void {
  if (!row.source_path) return;
  const next = new Map(selected.value);
  if (next.has(row.invoice_key)) next.delete(row.invoice_key);
  else next.set(row.invoice_key, entry(row));
  selected.value = next;
}

function togglePage(): void {
  const next = new Map(selected.value);
  if (pageState.value.all) for (const row of pageRows.value) next.delete(row.invoice_key);
  else for (const row of pageRows.value) next.set(row.invoice_key, entry(row));
  selected.value = next;
}

function clearSelection(): void {
  selectionGeneration += 1;
  selectingAll.value = false;
  selected.value = new Map();
  previewing.value = null;
}

function previewSelected(): void {
  if (!sourceActions.value || invoicesLoading.value || !selectedItems.value.length) return;
  // Preserve every selected source format, not the family-de-duplicated amount count.
  // preview-jobs alone validates these homepage identities against the active watch_dir.
  previewing.value = { target_id: invoices.value!.directory.target_id, items: selectedItems.value.map((item) => ({ ...item })) };
}

function previewSingle(item: SelectedInvoice): void {
  if (!sourceActions.value || invoicesLoading.value) return;
  previewing.value = { target_id: invoices.value!.directory.target_id, items: [{ ...item }] };
}

const queryFilters = () => [
  tagFilter.value && `&tag=${encodeURIComponent(tagFilter.value)}`,
  dateSort.value && `&date_sort=${dateSort.value}`,
  keyword.value.trim() && `&keyword=${encodeURIComponent(keyword.value.trim())}`,
  fileExt.value && `&file_ext=${encodeURIComponent(fileExt.value)}`,
  statusFilter.value && `&status=${encodeURIComponent(statusFilter.value)}`,
].filter(Boolean).join("");

function toggleDateSort(): void {
  dateSort.value = dateSort.value === "asc" ? "desc" : "asc";
  void loadInvoices(1);
}

async function selectAll(): Promise<void> {
  // The whole filtered result, not just this page: read every page with the same filters.
  if (!selectable.value || invoicesLoading.value) return;
  const mine = ++selectionGeneration;
  selectingAll.value = true;
  error.value = "";
  try {
    const filters = queryFilters();
    const revision = invoices.value?.snapshot?.revision;
    const next = new Map(selected.value);
    for (let page = 1; ; page += 1) {
      const payload = await request<DirectoryInvoicesPayload>(
        `${base()}/directories/${encodeURIComponent(props.dirKey)}/invoices?page=${page}&page_size=200${filters}`,
      );
      if (mine !== selectionGeneration) return;
      if (payload.read_only !== invoices.value?.read_only || payload.directory.target_id !== invoices.value?.directory.target_id ||
          payload.snapshot?.provisional || payload.snapshot?.revision !== revision) {
        throw new Error("目录或汇总已变化，请刷新后重新勾选。");
      }
      for (const row of payload.items) {
        if (row.source_path) next.set(row.invoice_key, entry(row));
      }
      if (page * 200 >= payload.count) break;
    }
    selected.value = next;
  } catch (cause) {
    if (mine === selectionGeneration) error.value = errorText(cause);
  } finally {
    if (mine === selectionGeneration) selectingAll.value = false;
  }
}

// The last delete's per-file result stays visible after the selection is cleared and the
// list reloads: a partial run must show which files moved and which did not.
const lastTrash = ref<TrashJob | null>(null);
const TRASH_LABELS: Record<string, string> = { pending: "未处理", moving: "结果待核对", trashed: "已移入废纸篓", failed: "未完成", unknown: "结果待核对" };

async function afterChange(job: TrashJob): Promise<void> {
  lastTrash.value = job;
  clearSelection();
  await loadInvoices(invoicesPage.value);
}

const base = () => `/api/v1/companies/${encodeURIComponent(props.company.id)}`;

async function loadInvoices(page = 1): Promise<void> {
  const mine = ++listGeneration;
  selectionGeneration += 1;
  selectingAll.value = false;
  invoicesLoading.value = true;
  error.value = "";
  try {
    const payload = await request<DirectoryInvoicesPayload>(
      `${base()}/directories/${encodeURIComponent(props.dirKey)}/invoices?page=${page}&page_size=${PAGE_SIZE}${queryFilters()}`,
    );
    if (mine !== listGeneration) return;
    // Pagination/sorting keep stable identities; a new projection or a monitor switch does not.
    // Dropping its selection also closes preview so old source paths cannot survive the change.
    if (payload.snapshot?.provisional || (invoices.value &&
        (invoices.value.snapshot?.revision !== payload.snapshot?.revision ||
         invoices.value.read_only !== payload.read_only || invoices.value.directory.target_id !== payload.directory.target_id))) clearSelection();
    invoices.value = payload;
    invoicesPage.value = payload.page ?? page;
  } catch (cause) {
    if (mine === listGeneration) error.value = errorText(cause);
  } finally {
    if (mine === listGeneration) invoicesLoading.value = false;
  }
}

const pageCount = () => Math.max(1, Math.ceil((invoices.value?.count ?? 0) / PAGE_SIZE));

function focusTagMenu(): void {
  void nextTick(() => {
    const menu = tagMenu.value, element = tagMenuEl.value;
    if (!menu || !element) return;
    // Async marks change menu height; keep mouse and keyboard menus reachable
    // at the window edge after either the initial render or the loaded marks.
    const box = element.getBoundingClientRect();
    menu.x = Math.max(8, Math.min(menu.x, window.innerWidth - box.width - 8));
    menu.y = Math.max(8, Math.min(menu.y, window.innerHeight - box.height - 8));
    element.querySelector<HTMLElement>("input, button")?.focus();
  });
}

function openTagMenu(row: InvoiceRow, event: MouseEvent | KeyboardEvent): void {
  columnMenuOpen.value = false;
  const target = event.currentTarget as HTMLElement;
  const box = target.getBoundingClientRect();
  const point = event instanceof MouseEvent && event.clientX ? { x: event.clientX, y: event.clientY } : { x: box.left + 24, y: box.bottom };
  // Like Finder: a row inside a multi-row selection tags the whole selection; any other row only itself.
  const rows = selectable.value && selected.value.size > 1 && selected.value.has(row.invoice_key) ? [...selected.value.values()] : null;
  const batch = rows && {
    // Several formats of one invoice share a number and so share their tags.
    numbers: [...new Set(rows.map((item) => item.invoice_number).filter(Boolean))],
    missing: rows.filter((item) => !item.invoice_number).length,
    revision: null,
    invoices: null,
  };
  tagMenu.value = { row, ...point, origin: target, batch };
  if (batch) void loadBatchMarks();
  // Keyboard users land in the menu; Escape returns them to the row they came from.
  focusTagMenu();
}

async function loadBatchMarks(): Promise<void> {
  const menu = tagMenu.value;
  if (!menu?.batch) return;
  try {
    const marks = await request<InvoiceTagMarks>(`${base()}/invoice-tags`);
    if (tagMenu.value !== menu) return; // closed or reopened meanwhile
    menu.batch.revision = marks.revision;
    menu.batch.invoices = marks.invoices;
    focusTagMenu();
  } catch (cause) {
    error.value = errorText(cause);
    closeTagMenu();
  }
}

function batchState(batch: BatchTags, tagId: string): { all: boolean; some: boolean } {
  const count = batch.numbers.filter((number) => batch.invoices?.[number]?.includes(tagId)).length;
  return { all: count > 0 && count === batch.numbers.length, some: count > 0 && count < batch.numbers.length };
}

async function toggleBatchTag(batch: BatchTags, tagId: string): Promise<void> {
  if (!batch.invoices || batch.revision === null) return;
  // All selected invoices have it: remove it from all. Otherwise add it where it is missing.
  const remove = batchState(batch, tagId).all;
  const changes: Record<string, string[]> = {};
  for (const number of batch.numbers) {
    const current = batch.invoices[number] ?? [];
    if (remove) changes[number] = current.filter((id) => id !== tagId);
    else if (!current.includes(tagId)) changes[number] = [...current, tagId];
  }
  if (!Object.keys(changes).length) return;
  tagBusy.value = true;
  error.value = "";
  try {
    const saved = await request<InvoiceTagMarks>(`${base()}/invoice-tags`, { method: "PUT", body: { revision: batch.revision, changes } });
    batch.revision = saved.revision;
    batch.invoices = saved.invoices;
    marksRevision.value = saved.revision;
    // The response holds every current mark: refresh this page's dots in place, no reload.
    for (const item of invoices.value?.items ?? []) {
      if (item.invoice_number) item.tags = saved.invoices[item.invoice_number] ?? [];
    }
  } catch (cause) {
    if (cause instanceof ApiError && cause.code === "INVOICE_TAGS_CONFLICT") {
      // Re-read the marks rather than replay: the user decides again on what is there now.
      batch.invoices = null;
      error.value = "标签已在别处修改，已重新读取，请再点一次。";
      await loadBatchMarks();
    } else {
      error.value = errorText(cause);
    }
  } finally {
    tagBusy.value = false;
  }
}

function closeTagMenu(): void {
  const origin = tagMenu.value?.origin;
  tagMenu.value = null;
  origin?.focus();
}

function onRowKey(row: InvoiceRow, event: KeyboardEvent): void {
  // Keyboard path to the same menu: the context-menu key or Shift+F10.
  if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
    event.preventDefault();
    openTagMenu(row, event);
  }
}

async function toggleTag(row: InvoiceRow, tagId: string): Promise<void> {
  if (!row.invoice_number) return;
  tagBusy.value = true;
  error.value = "";
  const current = row.tags ?? [];
  const next = current.includes(tagId) ? current.filter((id) => id !== tagId) : [...current, tagId];
  try {
    if (marksRevision.value === null) {
      marksRevision.value = (await request<InvoiceTagMarks>(`${base()}/invoice-tags`)).revision;
    }
    const saved = await request<InvoiceTagMarks>(`${base()}/invoice-tags`, {
      method: "PUT",
      body: { revision: marksRevision.value, changes: { [row.invoice_number]: next } },
    });
    marksRevision.value = saved.revision;
    // Local update only: the list keeps its page, order and scroll position.
    for (const item of invoices.value?.items ?? []) {
      if (item.invoice_number === row.invoice_number) item.tags = saved.invoices[row.invoice_number] ?? [];
    }
  } catch (cause) {
    if (cause instanceof ApiError && cause.code === "INVOICE_TAGS_CONFLICT") {
      marksRevision.value = null;
      error.value = "标签已在别处修改，已刷新列表，请重试。";
      await loadInvoices(invoicesPage.value);
    } else {
      error.value = errorText(cause);
    }
  } finally {
    tagBusy.value = false;
  }
}

function tagTitle(id: string): string {
  const tag = tagStore.byId.get(id);
  return tag ? (tag.meaning ? `${tag.name}：${tag.meaning}` : tag.name) : "";
}

// ---- manual project assignment (single row or batch selection, WS-03)
interface ProjectAssignModal {
  numbers: string[];
  missing: number;
  mode: "assign" | "unassign" | "restore";
  projectName: string;
  projectNames: string[];
  revision: number | null;
  loading: boolean;
  saving: boolean;
  error: string;
}
const projectModal = ref<ProjectAssignModal | null>(null);
let projectModalGeneration = 0;

async function openProjectAssign(targetRows?: { invoice_number: string }[]): Promise<void> {
  if (!isProjectDir.value) return;
  closeTagMenu();
  const mine = ++projectModalGeneration;
  const list = targetRows ?? [...selected.value.values()];
  const numbers = [...new Set(list.map((item) => item.invoice_number).filter(Boolean))];
  const missing = list.filter((item) => !item.invoice_number).length;
  const first = list[0];
  const currentProject = list.length === 1 && first && "project" in first ? String((first as InvoiceRow).project || "") : "";
  projectModal.value = {
    numbers,
    missing,
    mode: "assign",
    projectName: currentProject,
    projectNames: [],
    revision: null,
    loading: numbers.length > 0,
    saving: false,
    error: "",
  };
  if (!numbers.length) return;
  try {
    const summary = await request<ProjectSummary>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/projects?granularity=year`);
    if (mine !== projectModalGeneration || !projectModal.value) return;
    projectModal.value.revision = summary.assignments_revision;
    projectModal.value.projectNames = summary.project_names;
  } catch (cause) {
    if (mine === projectModalGeneration && projectModal.value) projectModal.value.error = errorText(cause);
  } finally {
    if (mine === projectModalGeneration && projectModal.value) projectModal.value.loading = false;
  }
}

async function saveProjectModal(): Promise<void> {
  const state = projectModal.value;
  if (!state || state.saving || state.revision === null || !state.numbers.length) return;
  const trimmed = state.projectName.trim().replace(/\s+/g, " ");
  if (state.mode === "assign" && !trimmed) {
    state.error = "请输入或选择项目名称。";
    return;
  }
  state.saving = true;
  state.error = "";
  try {
    const body: Record<string, unknown> = { revision: state.revision };
    if (state.mode === "assign") {
      body.assignments = Object.fromEntries(state.numbers.map((number) => [number, trimmed]));
    } else if (state.mode === "restore") {
      body.assignments = Object.fromEntries(state.numbers.map((number) => [number, ""]));
    } else {
      body.unassigned = state.numbers;
    }
    await request(`/api/v1/companies/${encodeURIComponent(props.company.id)}/projects/assignments`, {
      method: "PUT",
      body,
    });
    projectModal.value = null;
    toast(
      state.mode === "assign"
        ? `已将 ${state.numbers.length} 张发票归属至「${trimmed}」`
        : state.mode === "unassign"
          ? `已将 ${state.numbers.length} 张发票移出至未归属`
          : `已恢复 ${state.numbers.length} 张发票按备注识别项目`,
      "info",
      3000,
    );
    await loadInvoices(invoicesPage.value);
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
  } catch (cause) {
    state.error = cause instanceof ApiError && cause.code === "COMPANY_PROJECTS_CONFLICT"
      ? "项目归属已被修改，请关闭后重新打开。"
      : errorText(cause);
  } finally {
    state.saving = false;
  }
}

onMounted(() => {
  window.addEventListener("workspace:invoices-updated", refreshFromEvent);
  window.addEventListener("workspace:company-refreshed", onCompanyRefreshed);
  document.addEventListener("pointerdown", onDocumentPointerDown);
  document.addEventListener("keydown", onDocumentKeyDown, true);
  if (!tagStore.definitions) void tagStore.load();
});

// Source/monitor identity changes invalidate selection; a metadata-only object refresh does not.
watch(
  () => `${companySourceKey(props.company, [props.dirKey])}/${props.company.monitored}/${props.company.monitored_subdir_key ?? ""}`,
  () => {
    invoices.value = null;
    marksRevision.value = null;
    tagMenu.value = null;
    columnMenuOpen.value = false;
    clearSelection();
    void loadInvoices();
  },
  { immediate: true },
);
// A preview is a snapshot of this exact selection; changing it releases its heartbeat.
watch(() => JSON.stringify(selectedItems.value), () => { previewing.value = null; });
onBeforeUnmount(() => {
  clearTimeout(keywordTimer);
  listGeneration += 1;
  selectionGeneration += 1;
  window.removeEventListener("workspace:invoices-updated", refreshFromEvent);
  window.removeEventListener("workspace:company-refreshed", onCompanyRefreshed);
  document.removeEventListener("pointerdown", onDocumentPointerDown);
  document.removeEventListener("keydown", onDocumentKeyDown, true);
});
</script>

<template>
  <div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <section v-if="invoices" class="panel" aria-label="目录发票">
      <!-- Tag filtering, same-invoice deduplication and decimal totals all come from the server. -->
      <div v-if="invoices.stats?.all" class="dir-stats">
        <div class="overview-kpi"><span>全部记录</span><strong>{{ invoices.stats.all.total }}</strong><small>已识别 {{ invoices.stats.all.recognized }} 张</small></div>
        <div class="overview-kpi"><span>待核对</span><strong>{{ invoices.stats.all.needs_review }}</strong><small>金额或字段未识别</small></div>
        <div class="overview-kpi"><span>同票其他格式</span><strong>{{ invoices.stats.all.duplicates }}</strong><small>合计时只计一次</small></div>
        <div class="overview-kpi"><span>当前筛选合计</span><strong>{{ !invoices.stats.filtered ? "—" : money(String(invoices.stats.filtered.total_amount)) }}</strong><small>价税合计 · 同票只算一次 · 计入 {{ invoices.stats.filtered?.total_amount_valid_count ?? "—" }} 张<template v-if="invoices.stats.filtered?.total_amount_missing_count"> · 缺金额 {{ invoices.stats.filtered.total_amount_missing_count }} 张未计</template><template v-if="invoices.stats.filtered?.total_amount_conflict_count"> · 多格式金额不一 {{ invoices.stats.filtered.total_amount_conflict_count }} 张未计</template></small></div>
      </div>
      <div class="overview-section__head dir-list-head">
        <div>
          <h3>发票列表 <span class="muted">· {{ invoices.count }} 张</span> <span v-if="invoices.read_only" class="tag">只读 · 上次汇总</span></h3>
          <p>{{ selectable ? "勾选后底部会出现合计详情和批量操作；" : "" }}右键一行（或按 Shift+F10）可以打标签{{ selectable ? "，在已勾选的行上右键可批量打标签" : "" }}。</p>
        </div>
        <div v-if="invoices.directory.projection.summary_exists" class="dir-list-head__actions">
          <button
            v-if="hiddenColumns.length"
            type="button"
            class="ghost"
            @click="resetColumns"
          >恢复全部列</button>
          <div ref="columnMenuWrap" class="col-picker">
            <button
              ref="columnMenuTrigger"
              type="button"
              aria-haspopup="menu"
              :aria-expanded="columnMenuOpen"
              :aria-controls="columnMenuId"
              @click="toggleColumnMenu"
            >
              <WorkspaceIcon name="eye" />
              显示列
              <span v-if="hiddenColumns.length" class="col-picker__badge">已隐藏 {{ hiddenColumns.length }}</span>
            </button>
            <div
              v-if="columnMenuOpen"
              :id="columnMenuId"
              ref="columnMenuEl"
              class="col-picker__menu"
              role="menu"
              aria-label="自定义发票列表显示列"
              :style="columnMenuPos"
            >
              <div class="col-picker__head">
                <strong>显示列</strong>
                <button
                  type="button"
                  class="link"
                  :disabled="!hiddenColumns.length"
                  @click="resetColumns"
                >恢复全部</button>
              </div>
              <p class="col-picker__hint muted">取消勾选即可隐藏不需要的列（至少保留 1 列）。</p>
              <label
                v-for="col in availableColumns"
                :key="col.key"
                class="col-picker__item"
                role="menuitemcheckbox"
                :aria-checked="isColumnVisible(col.key) ? 'true' : 'false'"
              >
                <input
                  type="checkbox"
                  :checked="isColumnVisible(col.key)"
                  :disabled="isColumnVisible(col.key) && visibleColumnCount <= 1"
                  @change="onToggleColumn(col.key)"
                >
                <span>{{ col.label }}</span>
              </label>
            </div>
          </div>
        </div>
      </div>
      <p v-if="invoices.read_only" class="muted">未设为监控的目录可以直接查看、勾选并批量打标签；如需预览原票、打印或删除文件，请先设为监控目录。</p>
      <p v-if="!invoices.directory.projection.summary_exists" class="muted">这个目录还没读取过发票，点上方“读取数据”即可查看。</p>
      <p v-if="invoices.tags_error" class="banner banner--error" role="alert">标签读取失败，未显示：{{ invoices.tags_error }}</p>
      <p v-if="invoices.projects_error" class="banner banner--error" role="alert">{{ invoices.projects_error }}</p>
      <div class="filters">
        <label class="field">关键字<input v-model="keyword" aria-label="关键字" :placeholder="dirKey === 'issued_invoice_dir' ? '购买方 / 发票号 / 文件名' : '销售方 / 发票号 / 文件名'" @input="keywordChanged"></label>
        <label class="field">格式<select v-model="fileExt" aria-label="格式" @change="loadInvoices(1)"><option value="">全部</option><option value=".pdf">PDF</option><option value=".ofd">OFD</option><option value=".xml">XML</option></select></label>
        <label class="field">状态<select v-model="statusFilter" aria-label="状态" @change="loadInvoices(1)"><option value="">全部</option><option value="已识别">已识别</option><option value="待核对">待核对</option></select></label>
        <label v-if="tagStore.tags.length" class="field">标签<select v-model="tagFilter" aria-label="按标签筛选" @change="loadInvoices(1)">
          <option value="">全部</option>
          <option v-for="tag in tagStore.tags" :key="tag.id" :value="tag.id">{{ tag.name }}</option>
        </select></label>
      </div>
      <div v-if="invoices.directory.projection.summary_exists" class="directory-invoices-wrap">
        <table class="grid directory-invoices-table" :aria-busy="invoicesLoading">
          <thead>
            <tr @contextmenu.prevent="openColumnMenuAtHeader($event)">
              <th class="tag-cell"><span class="sr-only">标签</span></th>
              <th v-if="isColumnVisible('seller')" class="invoice-party">销售方</th>
              <th v-if="isColumnVisible('buyer')" class="invoice-party">购买方</th>
              <th v-if="isColumnVisible('format')">格式</th>
              <th v-if="isColumnVisible('invoice_number')">发票号码</th>
              <th v-if="isProjectDir && isColumnVisible('project')" class="invoice-project">项目</th>
              <th v-if="isColumnVisible('classification')">发票分类与业务</th>
              <th v-if="isColumnVisible('tax_rate')">税率</th>
              <th v-if="isColumnVisible('amount')" class="num">开票金额</th>
              <th v-if="isColumnVisible('invoice_date')" :aria-sort="dateSort === 'asc' ? 'ascending' : dateSort === 'desc' ? 'descending' : 'none'">
                <button type="button" class="link" :aria-label="dateSortLabel" @click="toggleDateSort">开票时间 {{ dateSort === 'asc' ? '↑' : dateSort === 'desc' ? '↓' : '↕' }}</button>
              </th>
              <th v-if="isColumnVisible('status')">状态</th>
              <th v-if="selectable" class="select-cell">
                <input
                  type="checkbox"
                  aria-label="勾选本页"
                  :checked="pageState.all"
                  :indeterminate.prop="pageState.some"
                  :disabled="!pageRows.length || invoicesLoading || selectingAll"
                  @change="togglePage"
                >
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in invoices.items"
              :key="row.invoice_key"
              tabindex="0"
              @contextmenu.prevent="openTagMenu(row, $event)"
              @keydown="onRowKey(row, $event)"
            >
              <!-- Fixed-width slot so names stay aligned; several tags stack like Finder dots. -->
              <td class="tag-cell">
                <span v-if="(row.tags ?? []).length" class="tag-dots">
                  <span v-for="id in row.tags ?? []" :key="id" class="tag-dot" :style="{ background: tagStore.byId.get(id)?.color }" :title="tagTitle(id)" />
                </span>
              </td>
              <td v-if="isColumnVisible('seller')" class="invoice-party">
                <span class="invoice-party__text" :title="row.seller || ''">{{ row.seller }}</span>
              </td>
              <td v-if="isColumnVisible('buyer')" class="invoice-party">
                <span class="invoice-party__text" :title="row.buyer || ''">{{ row.buyer }}</span>
              </td>
              <td v-if="isColumnVisible('format')" class="nowrap"><span class="format-badge" :class="`format-badge--${formatTone(row)}`">{{ formatLabel(row) }}</span></td>
              <td v-if="isColumnVisible('invoice_number')" class="nowrap">{{ row.invoice_number }}</td>
              <td v-if="isProjectDir && isColumnVisible('project')" class="invoice-project nowrap">
                <span class="invoice-project__text" :title="row.project ? (row.project_source === 'manual' ? `${row.project} · 人工` : row.project) : ''">
                  <template v-if="row.project">
                    <span>{{ row.project }}</span>
                    <small v-if="row.project_source === 'manual'" class="muted"> · 人工</small>
                  </template>
                  <span v-else class="muted">{{ row.project_source === "conflict" ? "备注冲突" : "—" }}</span>
                </span>
              </td>
              <td v-if="isColumnVisible('classification')" class="invoice-classification" :title="row.classification_issue || ''">
                <span class="invoice-type" :class="{ 'invoice-type--special': row.invoice_type === '增值税专用发票', 'invoice-type--ordinary': row.invoice_type === '增值税普通发票' }">{{ row.invoice_type || '—' }}</span>
                <span class="muted invoice-classification__business">业务：{{ row.business_type || '—' }}</span>
              </td>
              <td v-if="isColumnVisible('tax_rate')" class="nowrap">{{ ratePercent(row.tax_rate) }}</td>
              <td v-if="isColumnVisible('amount')" class="num">{{ money(row.amount) }}</td>
              <td v-if="isColumnVisible('invoice_date')" class="nowrap">{{ row.invoice_date }}</td>
              <td v-if="isColumnVisible('status')" class="nowrap"><span class="tag" :class="row.status === '已识别' ? 'pill-ok' : row.status ? 'pill-warn' : ''">{{ row.status || "—" }}</span></td>
              <td v-if="selectable" class="select-cell">
                <input
                  type="checkbox"
                  :aria-label="`勾选 ${row.invoice_number || row.source_file}`"
                  :checked="selected.has(row.invoice_key)"
                  :disabled="!row.source_path || invoicesLoading || selectingAll"
                  @change="toggleRow(row)"
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div
        v-if="tagMenu"
        ref="tagMenuEl"
        class="tag-menu"
        role="menu"
        :aria-label="tagMenu.batch ? `已勾选 ${selected.size} 张发票的标签` : `${tagMenu.row.invoice_number || tagMenu.row.source_file} 的标签`"
        :style="{ left: `${tagMenu.x}px`, top: `${tagMenu.y}px` }"
        @keydown.escape="closeTagMenu"
      >
        <template v-if="tagMenu.batch">
          <p class="muted">已勾选 {{ selected.size }} 张，{{ tagMenu.batch.numbers.length }} 个发票号码</p>
          <p v-if="tagMenu.batch.missing" class="muted">其中 {{ tagMenu.batch.missing }} 张没有发票号码，不会打标签。</p>
          <p v-if="!tagMenu.batch.numbers.length" class="muted">所选发票都没有发票号码，不能打标签。</p>
          <p v-else-if="!tagStore.tags.length" class="muted">还没有标签，请先在“标签”里添加。</p>
          <p v-else-if="!tagMenu.batch.invoices" class="muted" aria-busy="true">正在读取标签…</p>
          <template v-else>
            <label
              v-for="tag in tagStore.tags"
              :key="tag.id"
              role="menuitemcheckbox"
              :aria-checked="batchState(tagMenu.batch, tag.id).all ? 'true' : batchState(tagMenu.batch, tag.id).some ? 'mixed' : 'false'"
              :title="tag.meaning"
            >
              <input
                type="checkbox"
                :checked="batchState(tagMenu.batch, tag.id).all"
                :indeterminate.prop="batchState(tagMenu.batch, tag.id).some"
                :disabled="tagBusy"
                @change="toggleBatchTag(tagMenu.batch, tag.id)"
              >
              <span class="tag-dot" :style="{ background: tag.color }" /> {{ tag.name }}
            </label>
          </template>
        </template>
        <template v-else>
          <p v-if="!tagMenu.row.invoice_number" class="muted">没有发票号码，不能打标签。</p>
          <p v-else-if="!tagStore.tags.length" class="muted">还没有标签，请先在“标签”里添加。</p>
          <label v-for="tag in tagMenu.row.invoice_number ? tagStore.tags : []" :key="tag.id" role="menuitemcheckbox" :aria-checked="(tagMenu.row.tags ?? []).includes(tag.id)" :title="tag.meaning">
            <input type="checkbox" :checked="(tagMenu.row.tags ?? []).includes(tag.id)" :disabled="tagBusy" @change="toggleTag(tagMenu.row, tag.id)">
            <span class="tag-dot" :style="{ background: tag.color }" /> {{ tag.name }}
          </label>
        </template>
        <button
          v-if="isProjectDir"
          type="button"
          role="menuitem"
          @click="openProjectAssign(tagMenu.batch ? undefined : [tagMenu.row])"
        >{{ tagMenu.batch ? "批量调整项目归属…" : "调整项目归属…" }}</button>
        <button type="button" @click="closeTagMenu">关闭</button>
      </div>
      <div v-if="pageCount() > 1" class="actions">
        <button type="button" :disabled="invoicesLoading || invoicesPage <= 1" @click="loadInvoices(invoicesPage - 1)">上一页</button>
        <span class="muted">{{ invoicesPage }} / {{ pageCount() }}</span>
        <button type="button" :disabled="invoicesLoading || invoicesPage >= pageCount()" @click="loadInvoices(invoicesPage + 1)">下一页</button>
      </div>
      <div v-if="lastTrash" class="panel" role="status" aria-label="删除结果">
        <p>
          已移入废纸篓 {{ lastTrash.trashed_count }} / {{ lastTrash.files.length }} 个源文件<template v-if="lastTrash.state !== 'completed'">；其余文件未确认完成，请核对源目录与废纸篓，不会自动重复删除</template>。
          <button type="button" class="link" @click="lastTrash = null">关闭</button>
        </p>
        <ul v-if="lastTrash.state !== 'completed'" class="selection-bar__files">
          <li v-for="file in lastTrash.files" :key="file.name">{{ file.name }} <small class="muted">{{ file.message || TRASH_LABELS[file.status] || "" }}</small></li>
        </ul>
      </div>
      <p v-if="invoices.snapshot?.provisional" class="muted">正在整理的临时结果，整理完成后才能勾选。</p>
      <DirectorySelectionBar
        v-if="sourceActions && selected.size"
        :items="selectedItems"
        :target-id="invoices.directory.target_id"
        :total="invoices.count"
        :selecting-all="selectingAll || invoicesLoading"
        :can-assign-project="isProjectDir"
        @clear="clearSelection"
        @preview="previewSelected"
        @preview-item="previewSingle"
        @assign-project="openProjectAssign()"
        @select-all="selectAll"
        @changed="afterChange"
      />
      <div v-if="selectable && !sourceActions && selected.size" class="selection-bar" role="region" aria-label="批量标签">
        <strong>已勾选 {{ selected.size }} 张</strong>
        <span>右键或按 Shift+F10 可批量打标签</span>
        <button v-if="isProjectDir" type="button" class="sb-btn" :disabled="selectingAll || invoicesLoading" @click="openProjectAssign()">调整项目…</button>
        <button type="button" :disabled="selectingAll || invoicesLoading" @click="selectAll">全选筛选结果</button>
        <button type="button" aria-label="清除勾选" @click="clearSelection">×</button>
      </div>
      <SourcePreview v-if="previewing && sourceActions" label="已勾选发票" :preview="previewing" @close="previewing = null" />
      <WsModal
        v-if="projectModal"
        title="调整项目归属"
        :subtitle="`${company.name} · 已选 ${projectModal.numbers.length} 个发票号码（人工值优先于备注，重新汇总不会覆盖）`"
        @close="!projectModal.saving && (projectModal = null)"
      >
        <p v-if="projectModal.missing" class="muted">其中 {{ projectModal.missing }} 张没有发票号码，无法指定项目。</p>
        <p v-if="!projectModal.numbers.length" class="banner banner--error" role="alert">所选发票均缺少发票号码，无法调整项目归属。</p>
        <p v-else-if="projectModal.loading" class="muted" aria-busy="true">正在读取公司项目清单…</p>
        <form v-else class="stack" @submit.prevent="saveProjectModal">
          <div class="radios" role="radiogroup" aria-label="调整方式">
            <label><input v-model="projectModal.mode" type="radio" value="assign"> 指定到项目</label>
            <label><input v-model="projectModal.mode" type="radio" value="unassign"> 移出至未归属</label>
            <label><input v-model="projectModal.mode" type="radio" value="restore"> 恢复按发票备注识别</label>
          </div>
          <label v-if="projectModal.mode === 'assign'" class="field">
            项目名称
            <input
              v-model="projectModal.projectName"
              type="text"
              maxlength="60"
              list="dir-project-names"
              placeholder="输入新项目名或选择已有项目"
              aria-label="项目名称"
              :disabled="projectModal.saving"
            >
          </label>
          <datalist id="dir-project-names">
            <option v-for="name in projectModal.projectNames" :key="name" :value="name" />
          </datalist>
          <p v-if="projectModal.error" class="banner banner--error" role="alert">{{ projectModal.error }}</p>
          <div class="actions">
            <button type="submit" class="primary" :disabled="projectModal.saving" :aria-busy="projectModal.saving">
              {{ projectModal.saving ? "保存中…" : "确认保存" }}
            </button>
            <button type="button" class="ghost" :disabled="projectModal.saving" @click="projectModal = null">取消</button>
          </div>
        </form>
      </WsModal>
    </section>
  </div>
</template>
