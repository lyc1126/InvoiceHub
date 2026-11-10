<script setup lang="ts">
import { ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company, CompanyDirectory, DirectoriesPayload, DirectoryInvoicesPayload, SubdirCreateResult, SubdirPlan } from "../api/types";
import { FRESHNESS_LABELS, SUBDIR_STATUS_LABELS, errorText, money } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { useSystemStore } from "../stores/system";

const props = defineProps<{ company: Company }>();
const companies = useCompaniesStore();
const system = useSystemStore();

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
    invoices.value = await request<DirectoryInvoicesPayload>(
      `${base()}/directories/${encodeURIComponent(key)}/invoices?page=${page}&page_size=${PAGE_SIZE}`,
    );
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    invoicesLoading.value = false;
  }
}

const pageCount = () => Math.max(1, Math.ceil((invoices.value?.count ?? 0) / PAGE_SIZE));

watch(
  () => props.company.id,
  () => {
    plan.value = null;
    planResult.value = null;
    switchTarget.value = null;
    invoices.value = null;
    invoicesKey.value = "";
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
      <table v-else class="grid" :aria-busy="invoicesLoading">
        <thead>
          <tr><th>销售方</th><th>购买方</th><th>格式</th><th>发票号码</th><th>发票类型</th><th>税率</th><th class="num">开票金额</th><th>开票时间</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in invoices.items" :key="`${invoicesKey}:${row.invoice_key}`">
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
      <div v-if="pageCount() > 1" class="actions">
        <button type="button" :disabled="invoicesLoading || invoicesPage <= 1" @click="loadInvoices(invoicesKey, invoicesPage - 1)">上一页</button>
        <span class="muted">{{ invoicesPage }} / {{ pageCount() }}</span>
        <button type="button" :disabled="invoicesLoading || invoicesPage >= pageCount()" @click="loadInvoices(invoicesKey, invoicesPage + 1)">下一页</button>
      </div>
    </section>
  </section>
</template>
