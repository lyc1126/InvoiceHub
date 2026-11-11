<script setup lang="ts">
import { ref } from "vue";
import { request } from "../api/client";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { useSystemStore } from "../stores/system";

const props = defineProps<{ path: string }>();
const emit = defineEmits<{ done: []; cancel: [] }>();
const companies = useCompaniesStore();
const system = useSystemStore();
const busy = ref(false);
const error = ref("");

async function confirm(): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    // Same call as the classic homepage: the old monitor stops and a startup sync of the
    // new folder runs in the background. Still exactly one monitored directory.
    await request("/api/v1/settings", { method: "PUT", body: { watch_dir: props.path } });
    await Promise.all([system.refresh(), companies.load()]);
    emit("done");
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="panel" role="alertdialog" aria-label="设为监控目录">
    <p>把监控切换到 <strong class="path">{{ path }}</strong>？</p>
    <p class="muted">当前监控目录会停止监控；新目录会在后台自动汇总。同一时间只监控一个目录。</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <div class="actions">
      <button type="button" class="primary" :disabled="busy" :aria-busy="busy" @click="confirm">切换</button>
      <button type="button" :disabled="busy" @click="emit('cancel')">取消</button>
    </div>
  </div>
</template>
