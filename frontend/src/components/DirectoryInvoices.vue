<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company, DirectoryInvoicesPayload, InvoiceRow, InvoiceTagMarks } from "../api/types";
import { errorText, money } from "../format";
import { useTagsStore } from "../stores/tags";

// One company folder's invoice list (last projection; read-only unless it is the monitored
// folder). Shown in a directory tab of the workspace home; tags are display data only.
const props = defineProps<{ company: Company; dirKey: string }>();
const tagStore = useTagsStore();
const tagFilter = ref("");
// Revision of this company's 发票标签.json, read lazily before the first mark is saved.
const marksRevision = ref<number | null>(null);
const tagMenu = ref<{ row: InvoiceRow; x: number; y: number; origin: HTMLElement } | null>(null);
const tagMenuEl = ref<HTMLElement | null>(null);
const tagBusy = ref(false);
const error = ref("");
const invoices = ref<DirectoryInvoicesPayload | null>(null);
const invoicesPage = ref(1);
const invoicesLoading = ref(false);
const PAGE_SIZE = 50;

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
  tagMenu.value = { row, ...point, origin: target };
  // Keyboard users land in the menu; Escape returns them to the row they came from.
  void nextTick(() => tagMenuEl.value?.querySelector<HTMLElement>("input, button")?.focus());
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
        <span class="muted">右键一行（或 Shift+F10）打标签</span>
      </div>
      <table v-if="invoices.directory.projection.summary_exists" class="grid" :aria-busy="invoicesLoading">
        <thead>
          <tr><th class="tag-cell"><span class="sr-only">标签</span></th><th>销售方</th><th>购买方</th><th>格式</th><th>发票号码</th><th>发票类型</th><th>税率</th><th class="num">开票金额</th><th>开票时间</th><th>状态</th></tr>
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
          </tr>
        </tbody>
      </table>
      <div
        v-if="tagMenu"
        ref="tagMenuEl"
        class="tag-menu"
        role="menu"
        :aria-label="`${tagMenu.row.invoice_number || tagMenu.row.source_file} 的标签`"
        :style="{ left: `${tagMenu.x}px`, top: `${tagMenu.y}px` }"
        @keydown.escape="closeTagMenu"
      >
        <p v-if="!tagMenu.row.invoice_number" class="muted">没有发票号码，不能打标签。</p>
        <p v-else-if="!tagStore.tags.length" class="muted">还没有标签，请先在“标签”里添加。</p>
        <label v-for="tag in tagMenu.row.invoice_number ? tagStore.tags : []" :key="tag.id" role="menuitemcheckbox" :aria-checked="(tagMenu.row.tags ?? []).includes(tag.id)" :title="tag.meaning">
          <input type="checkbox" :checked="(tagMenu.row.tags ?? []).includes(tag.id)" :disabled="tagBusy" @change="toggleTag(tagMenu.row, tag.id)">
          <span class="tag-dot" :style="{ background: tag.color }" /> {{ tag.name }}
        </label>
        <button type="button" @click="closeTagMenu">关闭</button>
      </div>
      <div v-if="pageCount() > 1" class="actions">
        <button type="button" :disabled="invoicesLoading || invoicesPage <= 1" @click="loadInvoices(invoicesPage - 1)">上一页</button>
        <span class="muted">{{ invoicesPage }} / {{ pageCount() }}</span>
        <button type="button" :disabled="invoicesLoading || invoicesPage >= pageCount()" @click="loadInvoices(invoicesPage + 1)">下一页</button>
      </div>
    </section>
  </div>
</template>
