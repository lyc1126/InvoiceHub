<script setup lang="ts">
import { companySourceKey, useCompaniesStore } from "../stores/companies";
import { useWorkspaceStore } from "../stores/workspace";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { request } from "../api/client";
import type { BridgeRebuildPayload, Company, CompanyDirectory, CompanySubdir, DirectoriesPayload } from "../api/types";
import { FRESHNESS_LABELS, SUBDIR_STATUS_LABELS, errorText } from "../format";
import { REFRESHABLE_ROLES, effectiveFolderRole } from "../relations";
import { toast } from "../toast";
import BankLayouts from "./BankLayouts.vue";
import CompanyFolderDeleteModal from "./CompanyFolderDeleteModal.vue";
import CompanyFolderEditModal from "./CompanyFolderEditModal.vue";
import DirectoryInvoices from "./DirectoryInvoices.vue";
import PeriodFolderCheck from "./PeriodFolderCheck.vue";
import WatchSwitchConfirm from "./WatchSwitchConfirm.vue";

// A directory tab: one company folder with its freshness and role-dispatched capabilities. Only
// the active monitored folder has live notifications/file actions; non-monitored folders can
// read/update their local cache or run role-specific checks without switching watch_dir.
const props = defineProps<{ company: Company; dirKey: string }>();
const companies = useCompaniesStore();
const workspace = useWorkspaceStore();
const directory = ref<CompanyDirectory | null>(null);
const error = ref("");
const switching = ref(false);
const rebuilding = ref(false);
// Snapshot the target folder when opening edit/delete modals so an in-flight company reload
// triggered by updateFolder/removeFolder cannot unmount the modal before its `done` event fires.
const editTarget = ref<CompanySubdir | null>(null);
const deleteTarget = ref<CompanySubdir | null>(null);
const payrollPreview = ref<{ loading: boolean; error: string; months: { month: string; total: string; source: string }[]; unrecognized: { file: string; reason: string }[] } | null>(null);
const effectiveRole = computed(() => effectiveFolderRole(directory.value, props.dirKey));
const isInvoiceDir = computed(() => REFRESHABLE_ROLES.includes(effectiveRole.value));
const isCustomPayroll = computed(() => directory.value?.kind === "custom" && effectiveRole.value === "payroll_social_dir" && directory.value.status === "present");
const refreshState = computed(() => companies.refreshStates[props.company.id]);
const refreshing = computed(() => refreshState.value?.status === "running");

let loadGeneration = 0;
let rebuildGeneration = 0;
async function loadCustomPayroll(mine: number): Promise<void> {
  payrollPreview.value = { loading: true, error: "", months: [], unrecognized: [] };
  try {
    const res = await request<{ months?: { month: string; total?: string; source?: string }[]; unrecognized?: { file: string; reason: string }[] }>(
      `/api/v1/companies/${encodeURIComponent(props.company.id)}/payroll?dir_key=${encodeURIComponent(props.dirKey)}`,
    );
    if (mine !== loadGeneration) return;
    payrollPreview.value = {
      loading: false,
      error: "",
      months: (res.months ?? []).map((m) => ({ month: m.month, total: m.total ?? "—", source: m.source ?? "" })),
      unrecognized: res.unrecognized ?? [],
    };
  } catch (cause) {
    if (mine === loadGeneration) payrollPreview.value = { loading: false, error: errorText(cause), months: [], unrecognized: [] };
  }
}

async function load(): Promise<void> {
  const mine = ++loadGeneration;
  error.value = "";
  payrollPreview.value = null;
  try {
    const payload = await request<DirectoriesPayload>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/directories`);
    if (mine !== loadGeneration) return;
    directory.value = payload.directories.find((item) => item.key === props.dirKey) ?? null;
    if (!directory.value) {
      error.value = "公司清单里没有这个子目录。";
    } else if (directory.value.kind === "custom" && effectiveFolderRole(directory.value, props.dirKey) === "payroll_social_dir" && directory.value.status === "present") {
      void loadCustomPayroll(mine);
    }
  } catch (cause) {
    if (mine === loadGeneration) error.value = errorText(cause);
  }
}

function onEdited(nextKey?: string): void {
  editTarget.value = null;
  if (nextKey && nextKey !== props.dirKey) {
    workspace.closeDirectory(props.company.id, props.dirKey);
    workspace.open({ kind: "directory", companyId: props.company.id, dirKey: nextKey });
    return;
  }
  void load();
}

function onDeleted(result: { key: string; removedFromList: boolean }): void {
  deleteTarget.value = null;
  if (result.removedFromList) {
    workspace.closeDirectory(props.company.id, result.key);
  } else {
    void load();
  }
}

async function switched(): Promise<void> {
  switching.value = false;
  await load();
}

function readData(): void {
  void companies.refreshData(props.company.id, { keys: [props.dirKey], force: directory.value?.freshness.state !== "never_built" });
}

// Active monitored folders rebuild via the shared bridge endpoint so manual edits, cost
// workbooks and SSE consumers stay in sync with classic pages and the monitor daemon.
async function rebuildActive(): Promise<void> {
  if (rebuilding.value || !directory.value?.active) return;
  const mine = ++rebuildGeneration;
  const companyId = props.company.id;
  rebuilding.value = true;
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
    await load();
  } catch (cause) {
    if (mine === rebuildGeneration) error.value = errorText(cause);
  } finally {
    if (mine === rebuildGeneration) rebuilding.value = false;
  }
}

function onCompanyRefreshed(event: Event): void {
  const detail = (event as CustomEvent).detail;
  if (!detail?.companyId || detail.companyId === props.company.id) void load();
}

onMounted(() => window.addEventListener("workspace:company-refreshed", onCompanyRefreshed));
onBeforeUnmount(() => {
  ++loadGeneration;
  ++rebuildGeneration;
  rebuilding.value = false;
  window.removeEventListener("workspace:company-refreshed", onCompanyRefreshed);
});

// Source/monitor identity changes invalidate the displayed directory so stale paths never linger
// while loading; edit/delete modals hold their own target snapshot and only close when switching tabs.
let lastIdentity = "";
watch(
  () => `${companySourceKey(props.company, [props.dirKey])}/${props.company.monitored}/${props.company.monitored_subdir_key ?? ""}`,
  () => {
    const nextIdentity = `${props.company.id}:${props.dirKey}`;
    ++rebuildGeneration;
    rebuilding.value = false;
    directory.value = null;
    switching.value = false;
    if (nextIdentity !== lastIdentity) {
      editTarget.value = null;
      deleteTarget.value = null;
      lastIdentity = nextIdentity;
    }
    void load();
  },
  { immediate: true },
);
</script>

<template>
  <section class="directory-panel" :aria-label="`${company.name} · ${directory?.label ?? dirKey}`">
    <!-- Prototype dirHead: crumb / name / path on the left, monitoring chip on the right. The chip
         only states "current monitored directory" (not that the daemon runs), per WEB_UI rules. -->
    <header class="detail-header detail-header--split">
      <div>
        <p class="crumb">{{ company.name }} › {{ directory?.label ?? dirKey }}</p>
        <h2>
          {{ directory?.label ?? dirKey }}
          <span v-if="directory?.kind === 'custom'" class="tag">{{ directory.location === "external" ? "外部导入" : "自定义" }} · {{ directory.role_label || "普通资料" }}</span>
        </h2>
        <p class="muted path">{{ directory?.path ?? "" }}</p>
      </div>
      <div class="dir-head-actions">
        <span v-if="directory" class="status-chip" :class="{ 'status-chip--live': directory.active }"><i v-if="directory.active" class="ws-live" />{{ directory.active ? "当前监控目录" : "未监控 · 只读 · 上次汇总" }}</span>
        <button v-if="directory" type="button" class="ghost" @click="editTarget = directory">重命名 / 指向</button>
        <button v-if="directory" type="button" class="ghost" @click="deleteTarget = directory">移除 / 删除</button>
      </div>
    </header>
    <p v-if="directory?.kind === 'custom'" class="overview-notice">
      <span>
        该文件夹当前按「<strong>{{ directory.role_label || "普通资料" }}</strong>」基准独立提供功能，默认不自动计入公司总账、成本 V2 与凭证草稿{{ directory.location === "external" ? "（位于公司资料夹外）" : "；如需并入主流程可在「重命名 / 指向」中切换为主标准目录" }}。
      </span>
    </p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="refreshing" class="banner banner--note" role="status" aria-busy="true">{{ refreshState?.message || "正在后台读取发票数据…" }}</p>
    <p v-if="rebuilding" class="banner banner--note" role="status" aria-busy="true">正在重新汇总当前监控目录，完成后列表将自动更新…</p>
    <p v-if="directory?.status === 'present' && !directory.active" class="overview-notice overview-notice--warn">
      <span>{{ directory.freshness.state === 'never_built' ? '这个文件夹还没读取过数据，点“读取数据”即可直接查看，不需要切换监控目录。' : directory.freshness.parser_stale && !(directory.freshness.added || directory.freshness.updated || directory.freshness.deleted) ? '识别规则已更新，点“更新数据”即可重新汇总；如需实时监控和删除/打印原票再设为监控目录。' : '当前显示的是上次读取的数据；有新发票时可点“更新数据”，如需实时监控和删除/打印原票再设为监控目录。' }}</span>
      <button v-if="isInvoiceDir" type="button" class="primary" :disabled="refreshing" :aria-busy="refreshing" @click="readData">{{ refreshing ? "读取中…" : directory.freshness.state === "never_built" ? "读取数据" : "更新数据" }}</button>
      <button type="button" @click="switching = true">设为监控目录</button>
    </p>
    <div v-if="directory" class="toolbar directory-toolbar">
      <span>{{ SUBDIR_STATUS_LABELS[directory.status] }}</span>
      <span :class="`fresh fresh--${directory.freshness.state}`" :title="directory.freshness.message">{{ FRESHNESS_LABELS[directory.freshness.state] }}</span>
      <span class="muted">上次读取 {{ directory.projection.summary_updated_at || "—" }}</span>
      <button v-if="directory.status === 'present' && directory.active && isInvoiceDir" type="button" class="primary" :disabled="rebuilding" :aria-busy="rebuilding" @click="rebuildActive">{{ rebuilding ? "汇总中…" : "重新汇总" }}</button>
      <button type="button" :disabled="rebuilding" @click="load">检查变动</button>
    </div>
    <WatchSwitchConfirm v-if="switching && directory" :path="directory.path" @done="switched" @cancel="switching = false" />
    <!-- Folders kept by period (进项抵扣 / 银行流水 benchmark roles): content period vs. folder, confirmed moves (WS-05). -->
    <PeriodFolderCheck v-if="directory?.status === 'present' && (effectiveRole === 'input_deduction_dir' || effectiveRole === 'bank_flow_dir')" :company="company" :dir-key="dirKey" />
    <BankLayouts v-if="directory?.status === 'present' && effectiveRole === 'bank_flow_dir'" :company="company" :dir-key="dirKey" />
    <section v-if="isCustomPayroll && payrollPreview" class="overview-section" aria-label="自定义工资社保目录预览">
      <header class="overview-section__head"><div><h3>工资社保文件（只读）</h3><p>仅展示本自定义文件夹中识别到的社保应缴明细，不自动改写公司主申报数据。</p></div></header>
      <p v-if="payrollPreview.loading" class="muted" role="status" aria-busy="true">正在读取社保文件…</p>
      <p v-else-if="payrollPreview.error" class="banner banner--error" role="alert">{{ payrollPreview.error }}</p>
      <div v-else class="overview-table-wrap">
        <table class="grid">
          <thead><tr><th>费款所属期</th><th class="num">应缴费额合计</th><th>来源文件</th></tr></thead>
          <tbody>
            <tr v-for="m in payrollPreview.months" :key="m.month"><td>{{ m.month }}</td><td class="num">{{ m.total }}</td><td class="path mono">{{ m.source }}</td></tr>
            <tr v-if="!payrollPreview.months.length"><td colspan="3" class="muted">本目录中暂未识别到社保应缴明细表。</td></tr>
          </tbody>
        </table>
      </div>
      <p v-if="payrollPreview.unrecognized.length" class="muted">另有 {{ payrollPreview.unrecognized.length }} 个未识别文件。</p>
    </section>
    <DirectoryInvoices v-if="directory?.status === 'present'" :company="company" :dir-key="dirKey" />
    <p v-else-if="directory" class="muted">这个子目录{{ SUBDIR_STATUS_LABELS[directory.status] }}，没有可显示的发票。</p>

    <CompanyFolderEditModal v-if="editTarget" :company="company" :subdir="editTarget" @close="editTarget = null" @done="onEdited" />
    <CompanyFolderDeleteModal v-if="deleteTarget" :company="company" :subdir="deleteTarget" @close="deleteTarget = null" @done="onDeleted" />
  </section>
</template>

<style scoped>
.dir-head-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
</style>
