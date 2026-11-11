<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company, CompanyDirectory, DirectoriesPayload, DirectoryInvoicesPayload, InvoiceRow, InvoiceTagMarks, SubdirCreateResult, SubdirPlan } from "../api/types";
import { FRESHNESS_LABELS, SUBDIR_STATUS_LABELS, errorText, money } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { useSystemStore } from "../stores/system";
import { useTagsStore } from "../stores/tags";

const props = defineProps<{ company: Company }>();
const companies = useCompaniesStore();
const system = useSystemStore();
const tagStore = useTagsStore();
const tagFilter = ref("");
// Revision of this company's 发票标签.json, read lazily before the first mark is saved.
const marksRevision = ref<number | null>(null);
const tagMenu = ref<{ row: InvoiceRow; x: number; y: number; origin: HTMLElement } | null>(null);
const tagMenuEl = ref<HTMLElement | null>(null);
const tagBusy = ref(false);

const directories = ref<CompanyDirectory[]>([]);
const loading = ref(false);
const error = ref("");
const plan = ref<SubdirPlan | null>(null);
const planBusy = ref(false);
const planResult = ref<SubdirCreateResult | null>(null);
const switchTarget = ref<CompanyDirectory | null>(null);
const switchBusy = ref(false);
const invoicesKey = ref("");
const invoices = ref<DirectoryInvoicesPayload | null>(null);
const invoicesPage = ref(1);
const invoicesLoading = ref(false);
const PAGE_SIZE = 50;

const base = () => `/api/v1/companies/${encodeURIComponent(props.company.id)}`;

async function loadDirectories(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    // The freshness check is a bounded read-only comparison made only on this request;
    // nothing scans non-monitored folders in the background.
    directories.value = (await request<DirectoriesPayload>(`${base()}/directories`)).directories;
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    loading.value = false;
  }
}

async function previewSubdirs(): Promise<void> {
  planBusy.value = true;
  planResult.value = null;
  error.value = "";
  try {
    plan.value = await companies.subdirPlan(props.company.id);
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    planBusy.value = false;
  }
}

async function confirmSubdirs(): Promise<void> {
  if (!plan.value) return;
  planBusy.value = true;
  error.value = "";
  try {
    planResult.value = await companies.createSubdirs(props.company.id, plan.value.plan_hash);
    plan.value = null;
    await loadDirectories();
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.code === "COMPANY_PLAN_STALE" ? "目录状态在预览后变了，请重新预览。" : errorText(cause);
    plan.value = null;
  } finally {
    planBusy.value = false;
  }
}

async function switchWatchDir(): Promise<void> {
  if (!switchTarget.value) return;
  switchBusy.value = true;
  error.value = "";
  try {
    // Same call as the classic homepage: the old monitor stops and a startup sync of the
    // new folder runs in the background. Still exactly one monitored directory.
    await request("/api/v1/settings", { method: "PUT", body: { watch_dir: switchTarget.value.path } });
    switchTarget.value = null;
    await Promise.all([system.refresh(), companies.load()]);
    await loadDirectories();
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    switchBusy.value = false;
  }
}

async function loadInvoices(key: string, page = 1): Promise<void> {
  invoicesKey.value = key;
  invoicesPage.value = page;
  invoicesLoading.value = true;
  error.value = "";
  try {
    const tag = tagFilter.value ? `&tag=${encodeURIComponent(tagFilter.value)}` : "";
    invoices.value = await request<DirectoryInvoicesPayload>(
      `${base()}/directories/${encodeURIComponent(key)}/invoices?page=${page}&page_size=${PAGE_SIZE}${tag}`,
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
      await loadInvoices(invoicesKey.value, invoicesPage.value);
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

watch(
  () => props.company.id,
  () => {
    plan.value = null;
    planResult.value = null;
    switchTarget.value = null;
    invoices.value = null;
    invoicesKey.value = "";
    marksRevision.value = null;
    tagMenu.value = null;
    directories.value = [];
    void loadDirectories();
  },
  { immediate: true },
);
</script>

<template>
  <section aria-label="子目录">
    <div class="toolbar">
      <button type="button" :disabled="loading" :aria-busy="loading" @click="loadDirectories">{{ loading ? "检查中…" : "重新检查" }}</button>
      <button v-if="company.missing_subdir_count" type="button" :disabled="planBusy" @click="previewSubdirs">
        补建缺失子目录（{{ company.missing_subdir_count }}）
      </button>
    </div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

    <div v-if="plan" class="panel" aria-label="补建预览">
      <h3>将要创建 {{ plan.create_count }} 个空文件夹</h3>
      <p class="muted">只新建空文件夹，不移动、删除或改写任何已有文件。</p>
      <table class="grid">
        <thead><tr><th>类型</th><th>路径</th><th>处理</th></tr></thead>
        <tbody>
          <tr v-for="item in plan.items" :key="item.key" :class="{ 'row--danger': item.action === 'blocked' }">
            <td>{{ item.label }}</td>
            <td class="path">{{ item.relative_path }}</td>
            <td>{{ { create: "新建", exists: "已有，跳过", blocked: "不创建" }[item.action] }}<span v-if="item.reason" class="muted">：{{ item.reason }}</span></td>
          </tr>
        </tbody>
      </table>
      <div class="actions">
        <button type="button" class="primary" :disabled="planBusy || !plan.create_count" :aria-busy="planBusy" @click="confirmSubdirs">确认创建</button>
        <button type="button" :disabled="planBusy" @click="plan = null">取消</button>
      </div>
    </div>
    <p v-if="planResult" class="banner" :class="planResult.failed.length ? 'banner--error' : 'banner--ok'" role="status">
      已新建 {{ planResult.created.length }} 个<span v-if="planResult.skipped.length">，{{ planResult.skipped.length }} 个已存在而跳过</span><span v-if="planResult.failed.length">；失败：{{ planResult.failed.map((item) => item.message).join("；") }}</span>
    </p>

    <div v-if="switchTarget" class="panel" role="alertdialog" aria-label="设为监控目录">
      <p>把监控切换到 <strong class="path">{{ switchTarget.path }}</strong>？</p>
      <p class="muted">当前监控目录会停止监控；新目录会在后台自动汇总。同一时间只监控一个目录。</p>
      <div class="actions">
        <button type="button" class="primary" :disabled="switchBusy" :aria-busy="switchBusy" @click="switchWatchDir">切换</button>
        <button type="button" :disabled="switchBusy" @click="switchTarget = null">取消</button>
      </div>
    </div>

    <table class="grid">
      <thead>
        <tr><th>类型</th><th>子目录</th><th>状态</th><th>上次汇总</th><th>是否最新</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in directories" :key="item.key" :class="{ 'row--active': item.active }">
          <td>{{ item.label }}</td>
          <td class="path" :title="item.path">{{ item.relative_path }}</td>
          <td>{{ SUBDIR_STATUS_LABELS[item.status] }}</td>
          <td class="nowrap">{{ item.projection.summary_updated_at || "—" }}</td>
          <td :class="`fresh fresh--${item.freshness.state}`" :title="item.freshness.message">
            {{ FRESHNESS_LABELS[item.freshness.state] }}
            <span v-if="item.freshness.state === 'stale'" class="muted">（新增 {{ item.freshness.added }}、改动 {{ item.freshness.updated }}、删除 {{ item.freshness.deleted }}）</span>
          </td>
          <td class="row-actions">
            <button v-if="item.status === 'present'" type="button" @click="loadInvoices(item.key)">查看发票</button>
            <button v-if="item.status === 'present' && !item.active" type="button" @click="switchTarget = item">设为监控目录</button>
          </td>
        </tr>
      </tbody>
    </table>

    <section v-if="invoices" class="panel" aria-label="目录发票">
      <h3>
        {{ invoices.directory.label }} · {{ invoices.count }} 张
        <span v-if="invoices.read_only" class="tag">只读 · 上次汇总</span>
      </h3>
      <p v-if="invoices.read_only" class="muted">非监控目录只能查看；预览、打印、改名或删除请先设为监控目录。</p>
      <p v-if="!invoices.directory.projection.summary_exists" class="muted">这个目录还没有汇总过。</p>
      <p v-if="invoices.tags_error" class="banner banner--error" role="alert">标签读取失败，未显示：{{ invoices.tags_error }}</p>
      <div v-if="tagStore.tags.length" class="toolbar">
        <select v-model="tagFilter" aria-label="按标签筛选" @change="loadInvoices(invoicesKey, 1)">
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
            :key="`${invoicesKey}:${row.invoice_key}`"
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
        <button type="button" :disabled="invoicesLoading || invoicesPage <= 1" @click="loadInvoices(invoicesKey, invoicesPage - 1)">上一页</button>
        <span class="muted">{{ invoicesPage }} / {{ pageCount() }}</span>
        <button type="button" :disabled="invoicesLoading || invoicesPage >= pageCount()" @click="loadInvoices(invoicesKey, invoicesPage + 1)">下一页</button>
      </div>
    </section>
  </section>
</template>
