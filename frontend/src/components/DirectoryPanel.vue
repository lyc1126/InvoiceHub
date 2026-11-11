<script setup lang="ts">
import { ref, watch } from "vue";
import { request } from "../api/client";
import type { Company, CompanyDirectory, DirectoriesPayload } from "../api/types";
import { FRESHNESS_LABELS, SUBDIR_STATUS_LABELS, errorText } from "../format";
import DirectoryInvoices from "./DirectoryInvoices.vue";
import WatchSwitchConfirm from "./WatchSwitchConfirm.vue";

// A directory tab: one company folder with its freshness and invoice list. Only the folder
// the monitor watches is live; every other one shows its last projection read-only.
const props = defineProps<{ company: Company; dirKey: string }>();
const directory = ref<CompanyDirectory | null>(null);
const error = ref("");
const switching = ref(false);

async function load(): Promise<void> {
  error.value = "";
  try {
    const payload = await request<DirectoriesPayload>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/directories`);
    directory.value = payload.directories.find((item) => item.key === props.dirKey) ?? null;
    if (!directory.value) error.value = "公司清单里没有这个子目录。";
  } catch (cause) {
    error.value = errorText(cause);
  }
}

async function switched(): Promise<void> {
  switching.value = false;
  await load();
}

// A string key: a refreshed company list hands in a new object with the same id, which must not reload.
watch(() => `${props.company.id}/${props.dirKey}`, () => void load(), { immediate: true });
</script>

<template>
  <section class="directory-panel" :aria-label="`${company.name} · ${directory?.label ?? dirKey}`">
    <header class="detail-header">
      <h2>
        {{ company.name }} · {{ directory?.label ?? dirKey }}
        <span v-if="directory?.active" class="tag tag--accent">监控中</span>
        <span v-else-if="directory" class="tag">只读 · 上次汇总</span>
      </h2>
      <p class="muted path">{{ directory?.path ?? "" }}</p>
    </header>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <div v-if="directory" class="toolbar">
      <span>{{ SUBDIR_STATUS_LABELS[directory.status] }}</span>
      <span :class="`fresh fresh--${directory.freshness.state}`" :title="directory.freshness.message">{{ FRESHNESS_LABELS[directory.freshness.state] }}</span>
      <span class="muted">上次汇总 {{ directory.projection.summary_updated_at || "—" }}</span>
      <button type="button" @click="load">重新检查</button>
      <button v-if="directory.status === 'present' && !directory.active" type="button" @click="switching = true">设为监控目录</button>
    </div>
    <WatchSwitchConfirm v-if="switching && directory" :path="directory.path" @done="switched" @cancel="switching = false" />
    <DirectoryInvoices v-if="directory?.status === 'present'" :company="company" :dir-key="dirKey" />
    <p v-else-if="directory" class="muted">这个子目录{{ SUBDIR_STATUS_LABELS[directory.status] }}，没有可显示的发票。</p>
  </section>
</template>
