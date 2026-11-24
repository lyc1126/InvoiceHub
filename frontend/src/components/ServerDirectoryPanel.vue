<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { VIEW_ACTIVE } from "../modules";
import { request } from "../api/client";
import { errorText, money, ratePercent } from "../format";
import {
  CONNECTION_LABELS,
  PHASE_LABELS,
  formatBytes,
  isSourceRunning,
  type ServerInvoiceRow,
  type ServerSource,
  type ServerSummaryPayload,
  useSourcesStore,
} from "../stores/sources";
import { type InvoiceColumnKey, useWorkspaceStore } from "../stores/workspace";
import { toast } from "../toast";
import ServerPreviewDrawer from "./ServerPreviewDrawer.vue";
import ServerSelectionBar from "./ServerSelectionBar.vue";
import WorkspaceIcon from "./WorkspaceIcon.vue";

// Native InvoiceHub invoice table view for a read-only server directory (Option A).
// Reuses the same 4-KPI stats, multi-dimensional server-side filters/sorting/paging,
// column visibility, selection totals + cost breakdown, and batch source-bound preview,
// without mutating the remote server or switching the active monitor watch_dir.
const props = defineProps<{
  sourceId: string;
  parentId: string;
  active?: boolean;
}>();
const emit = defineEmits<{ openPanel: [sourceId: string] }>();

const store = useSourcesStore();
const workspace = useWorkspaceStore();
const viewActive = inject(VIEW_ACTIVE, ref(true));

const currentParentId = ref(props.parentId);
const summary = ref<ServerSummaryPayload | null>(null);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const keyword = ref("");
const fileExt = ref("");
const statusFilter = ref("");
const invoiceTypeFilter = ref("");
const dateSort = ref<"" | "asc" | "desc">("");
const page = ref(1);
const PAGE_SIZE = 50;

const selected = ref(new Map<string, ServerInvoiceRow>());
const selectingAll = ref(false);
const previewing = ref<{ entryIds: string[]; label: string } | null>(null);
const pendingPreview = ref<{ entryIds: string[]; label: string } | null>(null);

const source = computed(() => store.byId(props.sourceId));
const running = computed(() => isSourceRunning(source.value));
const progress = computed(() => source.value?.progress);
const isOnline = computed(() => source.value?.connection === "online");
const dirTitle = computed(() => summary.value?.scope_name || source.value?.name || "服务器目录");
const pageCount = computed(() => Math.max(1, Math.ceil((summary.value?.count ?? 0) / PAGE_SIZE)));
const dateSortLabel = computed(() => (dateSort.value === "asc" ? "按开票时间倒序排序" : "按开票时间正序排序"));

const ALL_COLUMNS: readonly { key: InvoiceColumnKey; label: string }[] = [
  { key: "seller", label: "销售方" },
  { key: "buyer", label: "购买方" },
  { key: "format", label: "格式" },
  { key: "invoice_number", label: "发票号码" },
  { key: "project", label: "文件位置" },
  { key: "classification", label: "发票分类与业务" },
  { key: "tax_rate", label: "税率" },
  { key: "amount", label: "开票金额" },
  { key: "invoice_date", label: "开票时间" },
  { key: "status", label: "状态" },
];
const COLUMN_PREF_KEY = "server_source";
const availableKeys = ALL_COLUMNS.map((col) => col.key);
const hiddenColumns = computed(() => workspace.hiddenColumnsFor(COLUMN_PREF_KEY, availableKeys));
const hiddenColumnSet = computed(() => new Set<InvoiceColumnKey>(hiddenColumns.value));
const visibleColumnCount = computed(() => ALL_COLUMNS.length - hiddenColumns.value.length);
const isColumnVisible = (key: InvoiceColumnKey) => !hiddenColumnSet.value.has(key);

const columnMenuId = `server-cols-${Math.random().toString(36).slice(2, 9)}`;
const columnMenuOpen = ref(false);
const columnMenuPos = ref({ left: "8px", top: "8px" });
const columnMenuWrap = ref<HTMLElement | null>(null);
const columnMenuTrigger = ref<HTMLButtonElement | null>(null);
const columnMenuEl = ref<HTMLElement | null>(null);

function positionColumnMenu(anchor?: { x: number; y: number }): void {
  void nextTick(() => {
    const el = columnMenuEl.value;
    if (!el || !columnMenuOpen.value) return;
    const box = el.getBoundingClientRect();
    const width = box.width || 220;
    const height = box.height || 300;
    const triggerBox = columnMenuTrigger.value?.getBoundingClientRect();
    let left = anchor ? anchor.x : triggerBox ? triggerBox.right - width : 8;
    let top = anchor ? anchor.y : triggerBox ? triggerBox.bottom + 6 : 8;
    if (!anchor && triggerBox && top + height > window.innerHeight - 8 && triggerBox.top - height - 6 >= 8) {
      top = triggerBox.top - height - 6;
    }
    columnMenuPos.value = {
      left: `${Math.max(8, Math.min(left, window.innerWidth - width - 8))}px`,
      top: `${Math.max(8, Math.min(top, window.innerHeight - height - 8))}px`,
    };
  });
}

function toggleColumnMenu(): void {
  columnMenuOpen.value = !columnMenuOpen.value;
  if (columnMenuOpen.value) positionColumnMenu();
}

function onToggleColumn(key: InvoiceColumnKey): void {
  workspace.toggleInvoiceColumn(COLUMN_PREF_KEY, key, availableKeys);
}

function resetColumns(): void {
  workspace.resetInvoiceColumns(COLUMN_PREF_KEY);
}

function onDocumentPointerDown(event: Event): void {
  if (!columnMenuOpen.value) return;
  const target = event.target as Node | null;
  if (target && (columnMenuWrap.value?.contains(target) || columnMenuEl.value?.contains(target))) return;
  columnMenuOpen.value = false;
}

const formatLabel = (row: ServerInvoiceRow) =>
  ["PDF", "OFD", "XML"].includes(row.file_format?.toUpperCase()) ? row.file_format.toUpperCase() : "未知";
const formatTone = (row: ServerInvoiceRow) => (formatLabel(row) === "未知" ? "unknown" : formatLabel(row).toLowerCase());

const selectedIds = computed(() => [...selected.value.keys()]);
const pageRows = computed(() => summary.value?.items ?? []);
const pageState = computed(() => {
  const count = pageRows.value.filter((row) => selected.value.has(row.entry_id)).length;
  return { all: count > 0 && count === pageRows.value.length, some: count > 0 && count < pageRows.value.length };
});

let loadTurn = 0;
let selectionTurn = 0;
let keywordTimer: ReturnType<typeof setTimeout> | undefined;
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let wasRunning = false;

function buildQuery(targetPage: number, size = PAGE_SIZE): string {
  const params = new URLSearchParams();
  if (currentParentId.value) params.set("parent_id", currentParentId.value);
  params.set("page", String(targetPage));
  params.set("page_size", String(size));
  if (keyword.value.trim()) params.set("keyword", keyword.value.trim());
  if (fileExt.value) params.set("file_ext", fileExt.value);
  if (statusFilter.value) params.set("status", statusFilter.value);
  if (invoiceTypeFilter.value) params.set("invoice_type", invoiceTypeFilter.value);
  if (dateSort.value) params.set("date_sort", dateSort.value);
  return params.toString();
}

function clearSelection(): void {
  selectionTurn += 1;
  selectingAll.value = false;
  selected.value = new Map();
  previewing.value = null;
}

function toggleRow(row: ServerInvoiceRow): void {
  const next = new Map(selected.value);
  if (next.has(row.entry_id)) next.delete(row.entry_id);
  else next.set(row.entry_id, row);
  selected.value = next;
}

function togglePage(): void {
  const next = new Map(selected.value);
  if (pageState.value.all) {
    for (const row of pageRows.value) next.delete(row.entry_id);
  } else {
    for (const row of pageRows.value) next.set(row.entry_id, row);
  }
  selected.value = next;
}

async function pollSource(): Promise<void> {
  clearTimeout(pollTimer);
  try {
    const res = await request<{ source: ServerSource }>(`/api/v1/sources/${props.sourceId}`);
    store.upsert(res.source);
    const nowRunning = isSourceRunning(res.source);
    if (nowRunning) {
      wasRunning = true;
      pollTimer = setTimeout(() => void pollSource(), 700);
      return;
    }
    if (wasRunning) {
      wasRunning = false;
      store.notifyUpdated();
      await loadSummary(page.value);
      if (pendingPreview.value) {
        const queued = pendingPreview.value;
        pendingPreview.value = null;
        if (!res.source.error && res.source.connection === "online") {
          previewing.value = queued;
        }
      }
    }
  } catch (cause) {
    error.value = errorText(cause);
  }
}

async function loadSummary(targetPage = 1): Promise<void> {
  const mine = ++loadTurn;
  selectionTurn += 1;
  selectingAll.value = false;
  loading.value = true;
  error.value = "";
  try {
    const [srcRes, sumRes] = await Promise.all([
      request<{ source: ServerSource }>(`/api/v1/sources/${props.sourceId}`),
      request<ServerSummaryPayload>(`/api/v1/sources/${props.sourceId}/summary?${buildQuery(targetPage)}`),
    ]);
    if (mine !== loadTurn) return;
    store.upsert(srcRes.source);
    if (summary.value?.generation && sumRes.generation && summary.value.generation !== sumRes.generation) {
      clearSelection();
    }
    summary.value = sumRes;
    page.value = sumRes.page ?? targetPage;
    if (isSourceRunning(srcRes.source)) {
      wasRunning = true;
      pollTimer = setTimeout(() => void pollSource(), 700);
    }
  } catch (cause) {
    if (mine === loadTurn) error.value = errorText(cause);
  } finally {
    if (mine === loadTurn) loading.value = false;
  }
}

function keywordChanged(): void {
  clearTimeout(keywordTimer);
  keywordTimer = setTimeout(() => void loadSummary(1), 300);
}

function toggleDateSort(): void {
  dateSort.value = dateSort.value === "asc" ? "desc" : "asc";
  void loadSummary(1);
}

async function navigateDirectory(nextParentId: string): Promise<void> {
  currentParentId.value = nextParentId;
  clearSelection();
  await loadSummary(1);
}

async function startTask(kind: string, extra: Record<string, unknown> = {}): Promise<void> {
  error.value = "";
  busy.value = true;
  try {
    const res = await request<{ source: ServerSource }>(`/api/v1/sources/${props.sourceId}/tasks`, {
      method: "POST",
      body: { kind, ...extra },
    });
    store.upsert(res.source);
    wasRunning = isSourceRunning(res.source);
    if (wasRunning) pollTimer = setTimeout(() => void pollSource(), 500);
    else await loadSummary(page.value);
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

async function cancelTask(): Promise<void> {
  error.value = "";
  pendingPreview.value = null;
  try {
    const res = await request<{ source: ServerSource }>(`/api/v1/sources/${props.sourceId}/cancel`, {
      method: "POST",
      body: {},
    });
    store.upsert(res.source);
    wasRunning = false;
    await loadSummary(page.value);
  } catch (cause) {
    error.value = errorText(cause);
  }
}

async function selectAllFiltered(): Promise<void> {
  if (!summary.value?.available || loading.value) return;
  const mine = ++selectionTurn;
  selectingAll.value = true;
  error.value = "";
  try {
    const expectedGen = summary.value.generation;
    const next = new Map(selected.value);
    for (let currentPage = 1; ; currentPage += 1) {
      const payload = await request<ServerSummaryPayload>(
        `/api/v1/sources/${props.sourceId}/summary?${buildQuery(currentPage, 200)}`,
      );
      if (mine !== selectionTurn) return;
      if (!payload.available || payload.generation !== expectedGen) {
        throw new Error("汇总代际已变化，请刷新后重新勾选。");
      }
      for (const row of payload.items ?? []) next.set(row.entry_id, row);
      if (currentPage * 200 >= (payload.count ?? 0)) break;
    }
    selected.value = next;
  } catch (cause) {
    if (mine === selectionTurn) error.value = errorText(cause);
  } finally {
    if (mine === selectionTurn) selectingAll.value = false;
  }
}

async function startBatchPreview(entryIds: string[], label: string): Promise<void> {
  if (!entryIds.length) return;
  if (entryIds.length > 100) {
    error.value = "单次批量预览最多支持 100 个源文件，请缩小勾选数量。";
    return;
  }
  error.value = "";
  const missing = entryIds.filter((id) => {
    const row = selected.value.get(id) ?? pageRows.value.find((item) => item.entry_id === id);
    return row ? !row.cached : false;
  });
  if (missing.length && !isOnline.value) {
    error.value = `选中的文件中有 ${missing.length} 个尚未下载离线副本，请连接服务器后再预览。`;
    return;
  }
  if (missing.length && isOnline.value) {
    pendingPreview.value = { entryIds, label };
    await startTask("download", { entry_ids: missing });
    return;
  }
  previewing.value = { entryIds, label };
}

function previewSelected(): void {
  void startBatchPreview(selectedIds.value, `已勾选 ${selectedIds.value.length} 个文件`);
}

function previewSingle(entryId: string): void {
  const row = selected.value.get(entryId) ?? pageRows.value.find((item) => item.entry_id === entryId);
  void startBatchPreview([entryId], row?.invoice_number || row?.source_file || "单张原票");
}

async function copyTableTsv(): Promise<void> {
  const rows = summary.value?.items ?? [];
  if (!rows.length) return;
  const cols = ALL_COLUMNS.filter((col) => isColumnVisible(col.key));
  const valueFor = (row: ServerInvoiceRow, key: InvoiceColumnKey): string => {
    switch (key) {
      case "seller": return row.seller || "";
      case "buyer": return row.buyer || "";
      case "format": return formatLabel(row);
      case "invoice_number": return row.invoice_number || "";
      case "project": return row.relative || row.source_file || "";
      case "classification": return [row.invoice_type, row.business_type].filter(Boolean).join(" / ");
      case "tax_rate": return ratePercent(row.tax_rate);
      case "amount": return row.amount || "";
      case "invoice_date": return row.invoice_date || "";
      case "status": return row.status || "";
    }
  };
  const clean = (v: string) => v.replace(/[\t\r\n]+/g, " ").trim();
  const lines = [
    cols.map((col) => col.label).join("\t"),
    ...rows.map((row) => cols.map((col) => clean(valueFor(row, col.key))).join("\t")),
  ];
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    toast(`已复制本页 ${rows.length} 条记录（TSV）`);
  } catch {
    error.value = "剪贴板写入失败，请手动选中表格复制。";
  }
}

watch(
  () => `${props.sourceId}:${props.parentId}`,
  () => {
    currentParentId.value = props.parentId;
    clearSelection();
    void loadSummary(1);
  },
  { immediate: true },
);

watch(
  () => store.revisionTick,
  () => {
    if (!running.value) void loadSummary(page.value);
  },
);

watch(viewActive, (active) => {
  if (!active) {
    columnMenuOpen.value = false;
    previewing.value = null;
  }
});

onMounted(() => {
  if (!store.sources.length) void store.load();
  document.addEventListener("pointerdown", onDocumentPointerDown);
});

onBeforeUnmount(() => {
  loadTurn += 1;
  selectionTurn += 1;
  clearTimeout(keywordTimer);
  clearTimeout(pollTimer);
  document.removeEventListener("pointerdown", onDocumentPointerDown);
});
</script>

<template>
  <section class="directory-panel server-dir-panel" :aria-label="`服务器目录 · ${dirTitle}`">
    <header class="detail-header detail-header--split">
      <div>
        <nav v-if="summary?.breadcrumbs?.length" class="crumb server-crumbs" aria-label="服务器目录层级">
          <button
            v-for="(crumb, idx) in summary.breadcrumbs"
            :key="crumb.id"
            type="button"
            class="link"
            @click="navigateDirectory(crumb.id)"
          >{{ crumb.name }}<span v-if="idx < summary.breadcrumbs.length - 1"> › </span></button>
        </nav>
        <p v-else class="crumb">服务器来源（只读）</p>
        <h2>{{ dirTitle }}</h2>
        <p v-if="source" class="muted path">{{ source.root }}</p>
      </div>
      <span v-if="source" class="status-chip" :class="{ 'status-chip--live': isOnline }">
        <i v-if="isOnline" class="ws-live" />
        服务器只读 · {{ CONNECTION_LABELS[source.connection] ?? source.connection }}
      </span>
    </header>

    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="source?.error" class="banner banner--error" role="alert">{{ source.error }}</p>

    <div v-if="running" class="banner banner--note server-task-banner" role="status" aria-busy="true">
      <div class="server-task-banner__row">
        <span>
          {{ PHASE_LABELS[progress?.phase ?? source?.sync ?? ""] ?? source?.sync }}
          <template v-if="progress?.total !== undefined"> · {{ progress.completed ?? 0 }} / {{ progress.total }}</template>
          <template v-else-if="progress?.enumerated !== undefined"> · 已枚举 {{ progress.enumerated }} 项</template>
          <template v-if="progress?.bytes !== undefined"> · {{ formatBytes(progress.bytes) }} / {{ formatBytes(progress.total_bytes ?? 0) }}</template>
        </span>
        <button type="button" class="ghost" @click="cancelTask">取消任务</button>
      </div>
      <progress :value="progress?.total ? progress.completed : undefined" :max="progress?.total ?? 1" />
    </div>

    <div class="toolbar directory-toolbar">
      <span class="tag">{{ summary?.available ? (summary.stale ? "上次汇总（未核验）" : "完整只读汇总") : "尚未汇总" }}</span>
      <span v-if="summary?.available" class="muted">
        上次汇总 {{ summary.last_complete_at || "—" }} · 解析 {{ summary.stats?.parsed ?? 0 }} / 复用 {{ summary.stats?.reused ?? 0 }}
      </span>
      <button type="button" class="ghost" @click="emit('openPanel', props.sourceId)">
        <WorkspaceIcon name="folder" />文件侧栏
      </button>
      <button
        v-if="!isOnline"
        type="button"
        class="primary"
        :disabled="running || busy"
        @click="startTask('scan')"
      >连接并刷新目录</button>
      <template v-else>
        <button
          type="button"
          class="primary"
          :disabled="running || busy"
          :aria-busy="running"
          @click="startTask('summary', { parent_id: currentParentId })"
        >{{ running ? "汇总中…" : summary?.available ? "增量汇总此目录" : "汇总此目录" }}</button>
        <button
          type="button"
          class="ghost"
          :disabled="running || busy"
          @click="startTask('summary', { parent_id: currentParentId, verify: true })"
        >校验内容</button>
        <button
          type="button"
          class="ghost"
          :disabled="running || busy"
          @click="startTask('summary', { parent_id: currentParentId, full: true })"
        >完整重建</button>
      </template>
      <button v-if="summary?.available && summary.items?.length" type="button" class="ghost" @click="copyTableTsv">
        <WorkspaceIcon name="copy" />复制本页
      </button>
    </div>

    <p v-if="summary?.cost_error" class="overview-notice overview-notice--warn">{{ summary.cost_error }}</p>

    <div v-if="summary && !summary.available" class="empty-state">
      <strong>「{{ dirTitle }}」尚未生成发票汇总</strong>
      <p class="muted">点击上方「汇总此目录」只下载并增量解析当前目录（含子目录）中的 PDF / OFD / XML 发票，不会改动服务器文件，也不会切换活动监控目录。</p>
      <button
        type="button"
        class="primary"
        :disabled="running || busy"
        @click="isOnline ? startTask('summary', { parent_id: currentParentId }) : startTask('scan')"
      >{{ isOnline ? "汇总此目录" : "连接并刷新目录" }}</button>
    </div>

    <section v-if="summary?.available" class="panel" aria-label="服务器目录发票列表">
      <div v-if="summary.invoice_stats?.all" class="dir-stats">
        <div class="overview-kpi">
          <span>全部记录</span>
          <strong>{{ summary.invoice_stats.all.total }}</strong>
          <small>已识别 {{ summary.invoice_stats.all.recognized }} 张</small>
        </div>
        <div class="overview-kpi">
          <span>待核对</span>
          <strong>{{ summary.invoice_stats.all.needs_review }}</strong>
          <small>金额、分类或字段未识别</small>
        </div>
        <div class="overview-kpi">
          <span>同票其他格式</span>
          <strong>{{ summary.invoice_stats.all.duplicates }}</strong>
          <small>合计时只计一次</small>
        </div>
        <div class="overview-kpi">
          <span>当前筛选合计</span>
          <strong>{{ money(summary.invoice_stats.filtered.total_amount) }}</strong>
          <small>
            价税合计 · 同票只算一次 · 计入 {{ summary.invoice_stats.filtered.total_amount_valid_count }} 张
            <template v-if="summary.invoice_stats.filtered.total_amount_missing_count"> · 缺金额 {{ summary.invoice_stats.filtered.total_amount_missing_count }} 张未计</template>
            <template v-if="summary.invoice_stats.filtered.total_amount_conflict_count"> · 多格式金额不一 {{ summary.invoice_stats.filtered.total_amount_conflict_count }} 张未计</template>
          </small>
        </div>
      </div>

      <div class="overview-section__head dir-list-head">
        <div>
          <h3>发票列表 <span class="muted">· {{ summary.count ?? 0 }} 条</span> <span class="tag">服务器只读</span></h3>
          <p class="muted">勾选后可查看同票去重合计、成本明细拆组并批量预览原票；{{ summary.scope }}</p>
        </div>
        <div class="dir-list-head__actions">
          <button v-if="hiddenColumns.length" type="button" class="ghost" @click="resetColumns">恢复全部列</button>
          <div ref="columnMenuWrap" class="col-picker">
            <button
              ref="columnMenuTrigger"
              type="button"
              aria-haspopup="menu"
              :aria-expanded="columnMenuOpen"
              :aria-controls="columnMenuId"
              @click="toggleColumnMenu"
            >
              <WorkspaceIcon name="eye" />显示列
              <span v-if="hiddenColumns.length" class="col-picker__badge">已隐藏 {{ hiddenColumns.length }}</span>
            </button>
            <div
              v-if="columnMenuOpen"
              :id="columnMenuId"
              ref="columnMenuEl"
              class="col-picker__menu"
              role="menu"
              aria-label="自定义服务器发票显示列"
              :style="columnMenuPos"
            >
              <div class="col-picker__head">
                <strong>显示列</strong>
                <button type="button" class="link" :disabled="!hiddenColumns.length" @click="resetColumns">恢复全部</button>
              </div>
              <label
                v-for="col in ALL_COLUMNS"
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

      <div class="filters">
        <label class="field">
          关键字
          <input v-model="keyword" aria-label="关键字" placeholder="销售方 / 购买方 / 发票号 / 文件名" @input="keywordChanged">
        </label>
        <label class="field">
          格式
          <select v-model="fileExt" aria-label="格式" @change="loadSummary(1)">
            <option value="">全部</option>
            <option value=".pdf">PDF</option>
            <option value=".ofd">OFD</option>
            <option value=".xml">XML</option>
          </select>
        </label>
        <label class="field">
          状态
          <select v-model="statusFilter" aria-label="状态" @change="loadSummary(1)">
            <option value="">全部</option>
            <option value="已识别">已识别</option>
            <option value="待核对">待核对</option>
            <option value="重复发票">重复发票</option>
          </select>
        </label>
        <label class="field">
          票种
          <select v-model="invoiceTypeFilter" aria-label="票种" @change="loadSummary(1)">
            <option value="">全部</option>
            <option value="增值税专用发票">增值税专用发票</option>
            <option value="增值税普通发票">增值税普通发票</option>
          </select>
        </label>
      </div>

      <div class="directory-invoices-wrap">
        <table class="grid directory-invoices-table" :aria-busy="loading">
          <thead>
            <tr>
              <th v-if="isColumnVisible('seller')" class="invoice-party">销售方</th>
              <th v-if="isColumnVisible('buyer')" class="invoice-party">购买方</th>
              <th v-if="isColumnVisible('format')">格式</th>
              <th v-if="isColumnVisible('invoice_number')">发票号码</th>
              <th v-if="isColumnVisible('project')" class="invoice-project">文件位置</th>
              <th v-if="isColumnVisible('classification')">发票分类与业务</th>
              <th v-if="isColumnVisible('tax_rate')">税率</th>
              <th v-if="isColumnVisible('amount')" class="num">开票金额</th>
              <th v-if="isColumnVisible('invoice_date')" :aria-sort="dateSort === 'asc' ? 'ascending' : dateSort === 'desc' ? 'descending' : 'none'">
                <button type="button" class="link" :aria-label="dateSortLabel" @click="toggleDateSort">
                  开票时间 {{ dateSort === "asc" ? "↑" : dateSort === "desc" ? "↓" : "↕" }}
                </button>
              </th>
              <th v-if="isColumnVisible('status')">状态</th>
              <th>原票</th>
              <th class="select-cell">
                <input
                  type="checkbox"
                  aria-label="勾选本页"
                  :checked="pageState.all"
                  :indeterminate.prop="pageState.some"
                  :disabled="!pageRows.length || loading || selectingAll"
                  @change="togglePage"
                >
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in pageRows" :key="row.entry_id">
              <td v-if="isColumnVisible('seller')" class="invoice-party">
                <span class="invoice-party__text" :title="row.seller || ''">{{ row.seller || "—" }}</span>
              </td>
              <td v-if="isColumnVisible('buyer')" class="invoice-party">
                <span class="invoice-party__text" :title="row.buyer || ''">{{ row.buyer || "—" }}</span>
              </td>
              <td v-if="isColumnVisible('format')" class="nowrap">
                <span class="format-badge" :class="`format-badge--${formatTone(row)}`">{{ formatLabel(row) }}</span>
              </td>
              <td v-if="isColumnVisible('invoice_number')" class="nowrap path">{{ row.invoice_number || "—" }}</td>
              <td v-if="isColumnVisible('project')" class="invoice-project">
                <span class="invoice-project__text path" :title="row.relative">{{ row.relative }}</span>
              </td>
              <td v-if="isColumnVisible('classification')" class="invoice-classification" :title="row.classification_issue || ''">
                <span
                  class="invoice-type"
                  :class="{
                    'invoice-type--special': row.invoice_type === '增值税专用发票',
                    'invoice-type--ordinary': row.invoice_type === '增值税普通发票',
                  }"
                >{{ row.invoice_type || "—" }}</span>
                <span class="muted invoice-classification__business">业务：{{ row.business_type || "—" }}</span>
              </td>
              <td v-if="isColumnVisible('tax_rate')" class="nowrap">{{ ratePercent(row.tax_rate) }}</td>
              <td v-if="isColumnVisible('amount')" class="num">{{ money(row.amount) }}</td>
              <td v-if="isColumnVisible('invoice_date')" class="nowrap">{{ row.invoice_date || "—" }}</td>
              <td v-if="isColumnVisible('status')" class="nowrap">
                <span class="tag" :class="row.status === '已识别' ? 'pill-ok' : row.status ? 'pill-warn' : ''">{{ row.status || "—" }}</span>
              </td>
              <td class="nowrap">
                <button
                  type="button"
                  class="link"
                  :disabled="!isOnline && !row.cached"
                  :title="!isOnline && !row.cached ? '离线且无本机副本' : row.cached ? '已缓存副本' : '按需下载并预览'"
                  @click="previewSingle(row.entry_id)"
                >预览</button>
              </td>
              <td class="select-cell">
                <input
                  type="checkbox"
                  :aria-label="`勾选 ${row.invoice_number || row.source_file}`"
                  :checked="selected.has(row.entry_id)"
                  :disabled="loading || selectingAll"
                  @change="toggleRow(row)"
                >
              </td>
            </tr>
            <tr v-if="!pageRows.length">
              <td :colspan="visibleColumnCount + 2" class="muted">没有符合当前筛选条件的发票记录。</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="pageCount > 1" class="actions">
        <button type="button" :disabled="loading || page <= 1" @click="loadSummary(page - 1)">上一页</button>
        <span class="muted">{{ page }} / {{ pageCount }}</span>
        <button type="button" :disabled="loading || page >= pageCount" @click="loadSummary(page + 1)">下一页</button>
      </div>
    </section>

    <ServerSelectionBar
      :source-id="props.sourceId"
      :parent-id="currentParentId"
      :generation="summary?.generation ?? ''"
      :entry-ids="selectedIds"
      :total="summary?.count ?? 0"
      :selecting-all="selectingAll"
      :preview-busy="!!pendingPreview && running"
      @clear="clearSelection"
      @select-all="selectAllFiltered"
      @preview="previewSelected"
      @preview-item="previewSingle"
    />

    <ServerPreviewDrawer
      v-if="previewing"
      :source-id="props.sourceId"
      :entry-ids="previewing.entryIds"
      :label="previewing.label"
      :allow-stale="!isOnline"
      @close="previewing = null"
    />
  </section>
</template>

<style scoped>
.server-crumbs { display: flex; flex-wrap: wrap; gap: 2px; align-items: center; }
.server-crumbs button { padding: 0; font-size: 13px; color: var(--muted); }
.server-task-banner { display: flex; flex-direction: column; gap: 6px; }
.server-task-banner__row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.server-task-banner progress { width: 100%; height: 4px; accent-color: #2778e5; }
</style>
