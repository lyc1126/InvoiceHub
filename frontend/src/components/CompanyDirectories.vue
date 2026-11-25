<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { BridgeRebuildPayload, Company, CompanyDirectory, CompanySubdir, DirectoriesPayload, SubdirCreateResult, SubdirPlan } from "../api/types";
import { FRESHNESS_LABELS, SUBDIR_STATUS_LABELS, errorText } from "../format";
import { REFRESHABLE_ROLES, effectiveFolderRole } from "../relations";
import { toast } from "../toast";
import { companySourceKey, useCompaniesStore } from "../stores/companies";
import { useWorkspaceStore } from "../stores/workspace";
import CompanyFolderCreateModal from "./CompanyFolderCreateModal.vue";
import CompanyFolderDeleteModal from "./CompanyFolderDeleteModal.vue";
import CompanyFolderEditModal from "./CompanyFolderEditModal.vue";
import WatchSwitchConfirm from "./WatchSwitchConfirm.vue";

const props = defineProps<{ company: Company }>();
const companies = useCompaniesStore();
const workspace = useWorkspaceStore();
const refreshState = computed(() => companies.refreshStates[props.company.id]);
const refreshing = computed(() => refreshState.value?.status === "running");

const directories = ref<CompanyDirectory[]>([]);
const visibleDirectories = computed(() => directories.value.filter((item) => !item.hidden));
const hiddenDirectories = computed(() => directories.value.filter((item) => item.hidden));
const loading = ref(false);
const error = ref("");
const plan = ref<SubdirPlan | null>(null);
const planKeys = ref<string[] | undefined>(undefined);
const planBusy = ref(false);
const planResult = ref<SubdirCreateResult | null>(null);
const switchTarget = ref<CompanyDirectory | null>(null);
const rebuildingActive = ref(false);
const createModalMode = ref<"create" | "import" | "restore" | null>(null);
const editTarget = ref<CompanySubdir | null>(null);
const deleteTarget = ref<CompanySubdir | null>(null);

function isRefreshable(item: CompanyDirectory): boolean {
  return REFRESHABLE_ROLES.includes(effectiveFolderRole(item));
}

function openActionLabel(item: CompanyDirectory): string {
  const role = effectiveFolderRole(item);
  return role === "bank_flow_dir" || role === "payroll_social_dir" || role === "general" ? "打开" : "查看发票";
}

function sourceBadge(item: CompanyDirectory): string {
  if (item.kind !== "custom") return "默认槽位";
  return item.location === "external" ? "外部导入" : "自定义";
}

function onFolderDeleted(result: { key: string; removedFromList: boolean }): void {
  deleteTarget.value = null;
  if (result.removedFromList) workspace.closeDirectory(props.company.id, result.key);
  void loadDirectories();
}

function onFolderEdited(): void {
  editTarget.value = null;
  void loadDirectories();
}

function onFolderCreated(folderId?: string): void {
  createModalMode.value = null;
  void loadDirectories();
  if (folderId) workspace.open({ kind: "directory", companyId: props.company.id, dirKey: folderId });
}

const base = () => `/api/v1/companies/${encodeURIComponent(props.company.id)}`;

let loadGeneration = 0;
let rebuildGeneration = 0;
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

async function rebuildActive(): Promise<void> {
  if (rebuildingActive.value) return;
  const mine = ++rebuildGeneration;
  const companyId = props.company.id;
  rebuildingActive.value = true;
  error.value = "";
  try {
    const payload = await request<BridgeRebuildPayload>("/api/v1/bridge/rebuild", {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (mine !== rebuildGeneration) return;
    if (!payload.ok) {
      error.value = payload.message || payload.error || "重新汇总失败，请稍后重试。";
      return;
    }
    toast(payload.message || "重新汇总已完成。");
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId } }));
    await loadDirectories();
  } catch (cause) {
    if (mine === rebuildGeneration) error.value = errorText(cause);
  } finally {
    if (mine === rebuildGeneration) rebuildingActive.value = false;
  }
}

function onCompanyRefreshed(event: Event): void {
  const detail = (event as CustomEvent).detail;
  if (!detail?.companyId || detail.companyId === props.company.id) void loadDirectories();
}

onMounted(() => window.addEventListener("workspace:company-refreshed", onCompanyRefreshed));
onBeforeUnmount(() => {
  ++loadGeneration;
  ++rebuildGeneration;
  rebuildingActive.value = false;
  window.removeEventListener("workspace:company-refreshed", onCompanyRefreshed);
});

watch(
  () => `${companySourceKey(props.company)}/${props.company.monitored}/${props.company.monitored_subdir_key ?? ""}`,
  () => {
    ++rebuildGeneration;
    rebuildingActive.value = false;
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
      <button type="button" class="primary" @click="createModalMode = 'create'">+ 新建 / 导入文件夹</button>
      <button v-if="hiddenDirectories.length" type="button" @click="createModalMode = 'restore'">
        已隐藏默认目录（{{ hiddenDirectories.length }}）
      </button>
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

    <div class="overview-table-wrap">
    <table class="grid">
      <thead>
        <tr><th>名称与功能指向</th><th>子目录路径</th><th>状态</th><th>上次汇总</th><th>是否最新</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in visibleDirectories" :key="item.key" :class="{ 'row--active': item.active }">
          <td>
            <strong>{{ item.label }}</strong>
            <div class="dir-meta-tags">
              <span class="tag">{{ sourceBadge(item) }}</span>
              <span v-if="item.kind === 'custom'" class="tag">{{ item.role_label || "普通资料" }}</span>
            </div>
          </td>
          <td class="path" :title="item.path">{{ item.relative_path }}</td>
          <td>{{ SUBDIR_STATUS_LABELS[item.status] }}</td>
          <td class="nowrap">{{ item.projection.summary_updated_at || "—" }}</td>
          <td :class="`fresh fresh--${item.freshness.state}`" :title="item.freshness.message">
            {{ FRESHNESS_LABELS[item.freshness.state] }}
            <span v-if="item.freshness.state === 'stale'" class="muted">{{ item.freshness.parser_stale && !(item.freshness.added || item.freshness.updated || item.freshness.deleted) ? "（识别规则已更新）" : `（新增 ${item.freshness.added}、改动 ${item.freshness.updated}、删除 ${item.freshness.deleted}）` }}</span>
          </td>
          <td class="row-actions">
            <button v-if="item.status === 'present'" type="button" @click="openDirectory(item)">{{ openActionLabel(item) }}</button>
            <button v-if="item.status === 'present' && item.active && isRefreshable(item)" type="button" :disabled="rebuildingActive" :aria-busy="rebuildingActive" @click="rebuildActive">{{ rebuildingActive ? "汇总中…" : "重新汇总" }}</button>
            <button v-if="item.status === 'present' && !item.active && isRefreshable(item)" type="button" :disabled="refreshing" @click="readDirectory(item)">{{ item.freshness.state === "never_built" ? "读取数据" : "更新数据" }}</button>
            <button v-if="item.status === 'present' && !item.active" type="button" @click="switchTarget = item">设为监控目录</button>
            <button v-if="item.status === 'missing' && item.kind !== 'custom'" type="button" :disabled="planBusy" @click="previewSubdirs([item.key])">创建文件夹</button>
            <button type="button" class="ghost" @click="editTarget = item">重命名 / 指向</button>
            <button type="button" class="ghost" @click="deleteTarget = item">移除 / 删除</button>
          </td>
        </tr>
      </tbody>
    </table>
    </div>

    <CompanyFolderCreateModal
      v-if="createModalMode"
      :company="company"
      :initial-mode="createModalMode"
      @close="createModalMode = null"
      @done="onFolderCreated"
    />
    <CompanyFolderEditModal
      v-if="editTarget"
      :company="company"
      :subdir="editTarget"
      @close="editTarget = null"
      @done="onFolderEdited"
    />
    <CompanyFolderDeleteModal
      v-if="deleteTarget"
      :company="company"
      :subdir="deleteTarget"
      @close="deleteTarget = null"
      @done="onFolderDeleted"
    />
  </section>
</template>

<style scoped>
.dir-meta-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.row-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.row-actions button { padding: 0 10px; }
</style>
