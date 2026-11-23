<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company, CompanyDirectory, DirectoriesPayload, SubdirCreateResult, SubdirPlan } from "../api/types";
import { FRESHNESS_LABELS, SUBDIR_STATUS_LABELS, errorText } from "../format";
import { companySourceKey, useCompaniesStore } from "../stores/companies";
import { useWorkspaceStore } from "../stores/workspace";
import WatchSwitchConfirm from "./WatchSwitchConfirm.vue";

const INVOICE_KEYS = new Set(["cost_invoice_dir", "issued_invoice_dir", "expense_reimbursement_dir"]);
const props = defineProps<{ company: Company }>();
const companies = useCompaniesStore();
const workspace = useWorkspaceStore();
const refreshState = computed(() => companies.refreshStates[props.company.id]);
const refreshing = computed(() => refreshState.value?.status === "running");

const directories = ref<CompanyDirectory[]>([]);
const loading = ref(false);
const error = ref("");
const plan = ref<SubdirPlan | null>(null);
const planKeys = ref<string[] | undefined>(undefined);
const planBusy = ref(false);
const planResult = ref<SubdirCreateResult | null>(null);
const switchTarget = ref<CompanyDirectory | null>(null);

const base = () => `/api/v1/companies/${encodeURIComponent(props.company.id)}`;

let loadGeneration = 0;
async function loadDirectories(): Promise<void> {
  const mine = ++loadGeneration;
  loading.value = true;
  error.value = "";
  try {
    // The freshness check is a bounded read-only comparison made only on this request;
    // nothing scans non-monitored folders in the background.
    const next = await request<DirectoriesPayload>(`${base()}/directories`);
    if (mine === loadGeneration) directories.value = next.directories;
  } catch (cause) {
    if (mine === loadGeneration) error.value = errorText(cause);
  } finally {
    if (mine === loadGeneration) loading.value = false;
  }
}

async function previewSubdirs(keys?: string[]): Promise<void> {
  planBusy.value = true;
  planResult.value = null;
  error.value = "";
  try {
    const sourceKey = companySourceKey(props.company);
    const next = await companies.subdirPlan(props.company.id, keys);
    if (sourceKey === companySourceKey(props.company)) {
      plan.value = next;
      planKeys.value = keys?.length ? [...keys] : undefined;
    }
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
    planResult.value = await companies.createSubdirs(props.company.id, plan.value.plan_hash, planKeys.value);
    plan.value = null;
    planKeys.value = undefined;
    await loadDirectories();
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.code === "COMPANY_PLAN_STALE" ? "目录状态在预览后变了，请重新预览。" : errorText(cause);
    plan.value = null;
    planKeys.value = undefined;
  } finally {
    planBusy.value = false;
  }
}

async function switched(): Promise<void> {
  switchTarget.value = null;
  await loadDirectories();
}

// The invoice list opens in its own directory tab of the workspace home.
function openDirectory(item: CompanyDirectory): void {
  workspace.open({ kind: "directory", companyId: props.company.id, dirKey: item.key });
}

function readDirectory(item?: CompanyDirectory): void {
  if (item) {
    void companies.refreshData(props.company.id, { keys: [item.key], force: item.freshness.state !== "never_built" });
  } else {
    void companies.refreshData(props.company.id);
  }
}

function onCompanyRefreshed(event: Event): void {
  const detail = (event as CustomEvent).detail;
  if (!detail?.companyId || detail.companyId === props.company.id) void loadDirectories();
}

onMounted(() => window.addEventListener("workspace:company-refreshed", onCompanyRefreshed));
onBeforeUnmount(() => window.removeEventListener("workspace:company-refreshed", onCompanyRefreshed));

watch(
  () => `${companySourceKey(props.company)}/${props.company.monitored}/${props.company.monitored_subdir_key ?? ""}`,
  () => {
    switchTarget.value = null;
    plan.value = null;
    planResult.value = null;
    directories.value = [];
    void loadDirectories();
  },
  { immediate: true },
);
</script>

<template>
  <section aria-label="子目录">
    <div class="toolbar">
      <button type="button" :disabled="loading" :aria-busy="loading" @click="loadDirectories">{{ loading ? "检查中…" : "检查变动" }}</button>
      <button v-if="company.missing_subdir_count" type="button" :disabled="planBusy" @click="previewSubdirs()">
        补建缺失子目录（{{ company.missing_subdir_count }}）
      </button>
      <button type="button" :disabled="refreshing" :aria-busy="refreshing" @click="readDirectory()">{{ refreshing ? "读取中…" : "读取全部发票" }}</button>
    </div>
    <p v-if="refreshing" class="banner banner--note" role="status" aria-busy="true">{{ refreshState?.message || "正在后台读取发票数据…" }}</p>
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

    <WatchSwitchConfirm v-if="switchTarget" :path="switchTarget.path" @done="switched" @cancel="switchTarget = null" />

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
            <button v-if="item.status === 'present'" type="button" @click="openDirectory(item)">查看发票</button>
            <button v-if="item.status === 'present' && !item.active && INVOICE_KEYS.has(item.key)" type="button" :disabled="refreshing" @click="readDirectory(item)">{{ item.freshness.state === "never_built" ? "读取数据" : "更新数据" }}</button>
            <button v-if="item.status === 'present' && !item.active" type="button" @click="switchTarget = item">设为监控目录</button>
            <button v-if="item.status === 'missing'" type="button" :disabled="planBusy" @click="previewSubdirs([item.key])">创建文件夹</button>
          </td>
        </tr>
      </tbody>
    </table>

  </section>
</template>
