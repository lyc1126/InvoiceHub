<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { request } from "../api/client";
import { errorText } from "../format";
import WsModal from "./WsModal.vue";

// Same contract as the classic settings dialog (web/static/js/system-controls.js): read the
// saved preference, confirm, POST /api/v1/server/shutdown once. A failed or unknown response
// is shown and only the user may retry; the shell never re-posts by itself.
type Behavior = "keep_monitor" | "stop_monitor";
const emit = defineEmits<{ close: [] }>();
const behavior = ref<Behavior>("keep_monitor");
const remember = ref(false);
const phase = ref<"loading" | "decide" | "busy" | "done">("loading");
const error = ref("");
const result = ref("");
const bridge = (window as unknown as { invoiceHubMac?: { backendOwnership?: string; canManageBackend?: boolean } }).invoiceHubMac;
// A desktop host that owns the backend must be quit from the host, not from the page.
const external = computed(() => !!bridge && (bridge.backendOwnership === "externalCompatible" || bridge.canManageBackend !== true));

onMounted(async () => {
  try {
    const payload = await request<{ preferences?: { system_shutdown_behavior?: string }; system_shutdown_behavior?: string }>("/api/v1/preferences");
    const saved = (payload.preferences ?? payload).system_shutdown_behavior;
    if (saved === "stop_monitor" || saved === "keep_monitor") behavior.value = saved;
  } catch {
    error.value = "关闭偏好读取失败，请确认本次选择。";
  }
  phase.value = "decide";
});

async function confirm(): Promise<void> {
  if (phase.value !== "decide" || external.value) return;
  phase.value = "busy";
  error.value = "";
  const chosen = behavior.value;
  try {
    const payload = await request<{ ok?: boolean; scheduled?: boolean; idempotent?: boolean; shutdown_behavior?: string; message?: string }>(
      "/api/v1/server/shutdown", { method: "POST", body: { shutdown_behavior: chosen, remember: remember.value } });
    if (!(payload.ok === true && (payload.scheduled === true || payload.idempotent === true) && payload.shutdown_behavior === chosen)) {
      throw new Error(payload.message || "后端未确认关闭请求，请重试。");
    }
    result.value = `${payload.message || "关闭命令已提交。"} 可关闭此浏览器页面；重新使用时请运行启动入口。`;
    phase.value = "done";
  } catch (cause) {
    error.value = errorText(cause) || "关闭系统失败，请重试。";
    phase.value = "decide";
  }
}
</script>

<template>
  <WsModal :title="phase === 'done' ? '关闭命令已提交' : '关闭本系统？'" :closable="phase !== 'busy' && phase !== 'done'" @close="emit('close')">
    <p v-if="phase === 'done'" role="status">{{ result }}</p>
    <template v-else>
      <p class="muted">关闭 WebUI 后，当前页面将无法继续操作。请选择是否让独立监控继续运行。</p>
      <p v-if="external" class="overview-notice overview-notice--warn"><span>本系统由桌面应用管理，请在应用菜单中退出。</span></p>
      <fieldset class="shutdown-options" :disabled="phase !== 'decide' || external">
        <legend>关闭后如何处理监控</legend>
        <label><input v-model="behavior" type="radio" value="keep_monitor"><span><b>保留监控，仅关闭 WebUI</b><small>独立监控继续处理当前发票目录的文件变化。</small></span></label>
        <label><input v-model="behavior" type="radio" value="stop_monitor"><span><b>关闭 WebUI，并停止监控</b><small>先等待独立监控退出，再关闭 localhost WebUI。</small></span></label>
      </fieldset>
      <label class="shutdown-remember"><input v-model="remember" type="checkbox" :disabled="phase !== 'decide' || external">记住本次选择</label>
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
      <div class="actions">
        <button type="button" class="danger-fill" :disabled="phase !== 'decide' || external" :aria-busy="phase === 'busy'" @click="confirm">{{ phase === "busy" ? "正在关闭…" : "确认关闭" }}</button>
        <button type="button" :disabled="phase === 'busy'" @click="emit('close')">取消</button>
      </div>
    </template>
  </WsModal>
</template>
