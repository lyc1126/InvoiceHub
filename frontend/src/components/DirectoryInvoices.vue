<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company, DirectoryInvoicesPayload, InvoiceRow, InvoiceTagMarks } from "../api/types";
import { errorText, money } from "../format";
import { useTagsStore } from "../stores/tags";
import DirectorySelectionBar, { type SelectedInvoice, type TrashJob } from "./DirectorySelectionBar.vue";

// One company folder's invoice list (last projection; read-only unless it is the monitored
// folder). Shown in a directory tab of the workspace home; tags are display data only.
const props = defineProps<{ company: Company; dirKey: string }>();
const tagStore = useTagsStore();
const tagFilter = ref("");
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
// Selection (WS-01 stage 2) only on the monitored folder's settled list: the actions behind it
// work on the current watch_dir, and a provisional first result has no stable row identity.
// The invoice number rides along for batch tagging only; the selection bar and every backend
// action still receive just `invoice_key + source_path`.
type SelectedRow = SelectedInvoice & { invoice_number: string };
const selected = ref(new Map<string, SelectedRow>());
const selectingAll = ref(false);
const selectable = computed(() => !!invoices.value && !invoices.value.read_only && !invoices.value.snapshot?.provisional);
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

async function selectAll(): Promise<void> {
  // The whole filtered result, not just this page: read every page with the same filters.
  selectingAll.value = true;
  error.value = "";
  try {
    const tag = tagFilter.value ? `&tag=${encodeURIComponent(tagFilter.value)}` : "";
    const next = new Map(selected.value);
    for (let page = 1; ; page += 1) {
      const payload = await request<DirectoryInvoicesPayload>(
        `${base()}/directories/${encodeURIComponent(props.dirKey)}/invoices?page=${page}&page_size=200${tag}`,
      );
      for (const row of payload.items) {
        if (row.source_path) next.set(row.invoice_key, entry(row));
      }
      if (page * 200 >= payload.count) break;
    }
    selected.value = next;
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    selectingAll.value = false;
  }
}

// The last delete's per-file result stays visible after the selection is cleared and the
// list reloads: a partial run must show which files moved and which did not.
const lastTrash = ref<TrashJob | null>(null);
const TRASH_LABELS: Record<string, string> = { pending: "未处理", moving: "结果待核对", trashed: "已移入废纸篓", failed: "未完成", unknown: "结果待核对" };

async function afterChange(job: TrashJob): Promise<void> {
  lastTrash.value = job;
  selected.value = new Map();
  await loadInvoices(invoicesPage.value);
}

const base = () => `/api/v1/companies/${encodeURIComponent(props.company.id)}`;

async function loadInvoices(page = 1): Promise<void> {
  invoicesPage.value = page;
  invoicesLoading.value = true;
  error.value = "";
  try {
    const tag = tagFilter.value ? `&tag=${encodeURIComponent(tagFilter.value)}` : "";
    invoices.value = await request<DirectoryInvoicesPayload>(
      `${base()}/directories/${encodeURIComponent(props.dirKey)}/invoices?page=${page}&page_size=${PAGE_SIZE}${tag}`,
    );
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    invoicesLoading.value = false;
  }
}

const pageCount = () => Math.max(1, Math.ceil((invoices.value?.count ?? 0) / PAGE_SIZE));

function openTagMenu(row: InvoiceRow, event: MouseEvent | KeyboardEvent): void {
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
  void nextTick(() => tagMenuEl.value?.querySelector<HTMLElement>("input, button")?.focus());
}

async function loadBatchMarks(): Promise<void> {
  const menu = tagMenu.value;
  if (!menu?.batch) return;
  try {
    const marks = await request<InvoiceTagMarks>(`${base()}/invoice-tags`);
    if (tagMenu.value !== menu) return; // closed or reopened meanwhile
    menu.batch.revision = marks.revision;
    menu.batch.invoices = marks.invoices;
    void nextTick(() => tagMenuEl.value?.querySelector<HTMLElement>("input, button")?.focus());
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

onMounted(() => {
  if (!tagStore.definitions) void tagStore.load();
});

// A string key: a refreshed company list hands in a new object with the same id, which must not reload.
watch(
  () => `${props.company.id}/${props.dirKey}`,
  () => {
    invoices.value = null;
    marksRevision.value = null;
    tagMenu.value = null;
    selected.value = new Map();
    void loadInvoices();
  },
  { immediate: true },
);
</script>

<template>
  <div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <section v-if="invoices" class="panel" aria-label="目录发票">
      <h3>
        {{ invoices.directory.label }} · {{ invoices.count }} 张
        <span v-if="invoices.read_only" class="tag">只读 · 上次汇总</span>
      </h3>
      <p v-if="invoices.read_only" class="muted">非监控目录只能查看；预览、打印、改名或删除请先设为监控目录。</p>
      <p v-if="!invoices.directory.projection.summary_exists" class="muted">这个目录还没有汇总过。</p>
      <p v-if="invoices.tags_error" class="banner banner--error" role="alert">标签读取失败，未显示：{{ invoices.tags_error }}</p>
      <div v-if="tagStore.tags.length" class="toolbar">
        <select v-model="tagFilter" aria-label="按标签筛选" @change="loadInvoices(1)">
          <option value="">全部标签</option>
          <option v-for="tag in tagStore.tags" :key="tag.id" :value="tag.id">{{ tag.name }}</option>
        </select>
        <span class="muted">右键一行（或 Shift+F10）打标签{{ selectable ? "；在已勾选的行上右键，给全部勾选的发票打标签" : "" }}</span>
      </div>
      <table v-if="invoices.directory.projection.summary_exists" class="grid" :aria-busy="invoicesLoading">
        <thead>
          <tr><th class="tag-cell"><span class="sr-only">标签</span></th><th>销售方</th><th>购买方</th><th>格式</th><th>发票号码</th><th>发票类型</th><th>税率</th><th class="num">开票金额</th><th>开票时间</th><th>状态</th>
            <th v-if="selectable" class="select-cell">
              <input
                type="checkbox"
                aria-label="勾选本页"
                :checked="pageState.all"
                :indeterminate.prop="pageState.some"
                :disabled="!pageRows.length"
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
              <span v-for="id in row.tags ?? []" :key="id" class="tag-dot" :style="{ background: tagStore.byId.get(id)?.color }" :title="tagTitle(id)" />
            </td>
            <td>{{ row.seller }}</td>
            <td>{{ row.buyer }}</td>
            <td class="nowrap">{{ row.file_format }}</td>
            <td class="nowrap">{{ row.invoice_number }}</td>
            <td>{{ row.invoice_type }}</td>
            <td class="nowrap">{{ row.tax_rate }}</td>
            <td class="num">{{ money(row.amount) }}</td>
            <td class="nowrap">{{ row.invoice_date }}</td>
            <td class="nowrap">{{ row.status }}</td>
            <td v-if="selectable" class="select-cell">
              <input
                type="checkbox"
                :aria-label="`勾选 ${row.invoice_number || row.source_file}`"
                :checked="selected.has(row.invoice_key)"
                :disabled="!row.source_path"
                @change="toggleRow(row)"
              >
            </td>
          </tr>
        </tbody>
      </table>
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
        v-if="selectable && selected.size"
        :items="selectedItems"
        :target-id="invoices.directory.target_id"
        :total="invoices.count"
        :selecting-all="selectingAll"
        @clear="selected = new Map()"
        @select-all="selectAll"
        @changed="afterChange"
      />
    </section>
  </div>
</template>
