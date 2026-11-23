<script setup lang="ts">
import { companySourceKey, useCompaniesStore } from "../stores/companies";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { request } from "../api/client";
import type { Company, CompanyDirectory, DirectoriesPayload } from "../api/types";
import { FRESHNESS_LABELS, SUBDIR_STATUS_LABELS, errorText } from "../format";
import BankLayouts from "./BankLayouts.vue";
import DirectoryInvoices from "./DirectoryInvoices.vue";
import PeriodFolderCheck from "./PeriodFolderCheck.vue";
import WatchSwitchConfirm from "./WatchSwitchConfirm.vue";

// A directory tab: one company folder with its freshness and invoice list. Only the folder
// the monitor watches has live notifications/file actions; non-monitored invoice folders can
// read/update their local cache without switching watch_dir or writing into the source folder.
const INVOICE_KEYS = new Set(["cost_invoice_dir", "issued_invoice_dir", "expense_reimbursement_dir"]);
const props = defineProps<{ company: Company; dirKey: string }>();
const companies = useCompaniesStore();
const directory = ref<CompanyDirectory | null>(null);
const error = ref("");
const switching = ref(false);
const isInvoiceDir = computed(() => INVOICE_KEYS.has(props.dirKey));
const refreshState = computed(() => companies.refreshStates[props.company.id]);
const refreshing = computed(() => refreshState.value?.status === "running");

let loadGeneration = 0;
async function load(): Promise<void> {
  const mine = ++loadGeneration;
  error.value = "";
  try {
    const payload = await request<DirectoriesPayload>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/directories`);
    if (mine !== loadGeneration) return;
    directory.value = payload.directories.find((item) => item.key === props.dirKey) ?? null;
    if (!directory.value) error.value = "公司清单里没有这个子目录。";
  } catch (cause) {
    if (mine === loadGeneration) error.value = errorText(cause);
  }
}

async function switched(): Promise<void> {
  switching.value = false;
  await load();
}

function readData(): void {
  void companies.refreshData(props.company.id, { keys: [props.dirKey], force: directory.value?.freshness.state !== "never_built" });
}

function onCompanyRefreshed(event: Event): void {
  const detail = (event as CustomEvent).detail;
  if (!detail?.companyId || detail.companyId === props.company.id) void load();
}

onMounted(() => window.addEventListener("workspace:company-refreshed", onCompanyRefreshed));
onBeforeUnmount(() => window.removeEventListener("workspace:company-refreshed", onCompanyRefreshed));

// Source/monitor identity changes invalidate the directory; a metadata-only object refresh does not.
watch(() => `${companySourceKey(props.company, [props.dirKey])}/${props.company.monitored}/${props.company.monitored_subdir_key ?? ""}`, () => { directory.value = null; switching.value = false; void load(); }, { immediate: true });
</script>

<template>
  <section class="directory-panel" :aria-label="`${company.name} · ${directory?.label ?? dirKey}`">
    <!-- Prototype dirHead: crumb / name / path on the left, monitoring chip on the right. The chip
         only states "current monitored directory" (not that the daemon runs), per WEB_UI rules. -->
    <header class="detail-header detail-header--split">
      <div>
        <p class="crumb">{{ company.name }} › {{ directory?.label ?? dirKey }}</p>
        <h2>{{ directory?.label ?? dirKey }}</h2>
        <p class="muted path">{{ directory?.path ?? "" }}</p>
      </div>
      <span v-if="directory" class="status-chip" :class="{ 'status-chip--live': directory.active }"><i v-if="directory.active" class="ws-live" />{{ directory.active ? "当前监控目录" : "未监控 · 只读 · 上次汇总" }}</span>
    </header>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="refreshing" class="banner banner--note" role="status" aria-busy="true">{{ refreshState?.message || "正在后台读取发票数据…" }}</p>
    <p v-if="directory?.status === 'present' && !directory.active" class="overview-notice overview-notice--warn">
      <span>{{ directory.freshness.state === 'never_built' ? '这个文件夹还没读取过数据，点“读取数据”即可直接查看，不需要切换监控目录。' : '当前显示的是上次读取的数据；有新发票时可点“更新数据”，如需实时监控和删除/打印原票再设为监控目录。' }}</span>
      <button v-if="isInvoiceDir" type="button" class="primary" :disabled="refreshing" :aria-busy="refreshing" @click="readData">{{ refreshing ? "读取中…" : directory.freshness.state === "never_built" ? "读取数据" : "更新数据" }}</button>
      <button type="button" @click="switching = true">设为监控目录</button>
    </p>
    <div v-if="directory" class="toolbar directory-toolbar">
      <span>{{ SUBDIR_STATUS_LABELS[directory.status] }}</span>
      <span :class="`fresh fresh--${directory.freshness.state}`" :title="directory.freshness.message">{{ FRESHNESS_LABELS[directory.freshness.state] }}</span>
      <span class="muted">上次读取 {{ directory.projection.summary_updated_at || "—" }}</span>
      <button type="button" @click="load">检查变动</button>
    </div>
    <WatchSwitchConfirm v-if="switching && directory" :path="directory.path" @done="switched" @cancel="switching = false" />
    <!-- Folders kept by period (进项抵扣 / 银行流水): content period vs. folder, confirmed moves (WS-05). -->
    <PeriodFolderCheck v-if="directory?.status === 'present' && (dirKey === 'input_deduction_dir' || dirKey === 'bank_flow_dir')" :company="company" :dir-key="dirKey" />
    <BankLayouts v-if="directory?.status === 'present' && dirKey === 'bank_flow_dir'" :company="company" />
    <DirectoryInvoices v-if="directory?.status === 'present'" :company="company" :dir-key="dirKey" />
    <p v-else-if="directory" class="muted">这个子目录{{ SUBDIR_STATUS_LABELS[directory.status] }}，没有可显示的发票。</p>
  </section>
</template>
