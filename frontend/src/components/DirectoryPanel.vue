<script setup lang="ts">
import { companySourceKey } from "../stores/companies";
import { ref, watch } from "vue";
import { request } from "../api/client";
import type { Company, CompanyDirectory, DirectoriesPayload } from "../api/types";
import { FRESHNESS_LABELS, SUBDIR_STATUS_LABELS, errorText } from "../format";
import BankLayouts from "./BankLayouts.vue";
import DirectoryInvoices from "./DirectoryInvoices.vue";
import PeriodFolderCheck from "./PeriodFolderCheck.vue";
import WatchSwitchConfirm from "./WatchSwitchConfirm.vue";

// A directory tab: one company folder with its freshness and invoice list. Only the folder
// the monitor watches is live; every other one shows its last projection read-only.
const props = defineProps<{ company: Company; dirKey: string }>();
const directory = ref<CompanyDirectory | null>(null);
const error = ref("");
const switching = ref(false);

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
    <p v-if="directory?.status === 'present' && !directory.active" class="overview-notice overview-notice--warn">
      <span>当前看到的是该目录上次汇总的结果；新放进来的发票要重新汇总，或把它设为监控目录。</span>
      <button type="button" @click="switching = true">设为监控目录</button>
    </p>
    <div v-if="directory" class="toolbar directory-toolbar">
      <span>{{ SUBDIR_STATUS_LABELS[directory.status] }}</span>
      <span :class="`fresh fresh--${directory.freshness.state}`" :title="directory.freshness.message">{{ FRESHNESS_LABELS[directory.freshness.state] }}</span>
      <span class="muted">上次汇总 {{ directory.projection.summary_updated_at || "—" }}</span>
      <button type="button" @click="load">重新检查</button>
    </div>
    <WatchSwitchConfirm v-if="switching && directory" :path="directory.path" @done="switched" @cancel="switching = false" />
    <!-- Folders kept by period (进项抵扣 / 银行流水): content period vs. folder, confirmed moves (WS-05). -->
    <PeriodFolderCheck v-if="directory?.status === 'present' && (dirKey === 'input_deduction_dir' || dirKey === 'bank_flow_dir')" :company="company" :dir-key="dirKey" />
    <BankLayouts v-if="directory?.status === 'present' && dirKey === 'bank_flow_dir'" :company="company" />
    <DirectoryInvoices v-if="directory?.status === 'present'" :company="company" :dir-key="dirKey" />
    <p v-else-if="directory" class="muted">这个子目录{{ SUBDIR_STATUS_LABELS[directory.status] }}，没有可显示的发票。</p>
  </section>
</template>
