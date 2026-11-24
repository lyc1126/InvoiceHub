<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { request } from "../api/client";
import type { SkinsPayload } from "../api/types";
import { prepareSkinStylesheet, setSkinIdentity, workspaceSkinIsolated } from "../appearance";

const props = defineProps<{ recovery: boolean }>();
const emit = defineEmits<{ changed: [] }>();
const DARK = "website-dark";
const activeId = ref(document.documentElement.dataset.activeSkin ?? "");
const busy = ref(false);
const error = ref("");
const dark = computed(() => activeId.value === DARK);
const label = computed(() => props.recovery ? "恢复模式：浅色外观" : dark.value ? "切换浅色外观" : "切换深色外观");
let controller: AbortController | undefined;
let mounted = true;
let prepared: HTMLLinkElement | undefined;
let syncQueued = false;

function apply(id: string): void {
  document.getElementById("activeSkinStylesheet")?.remove();
  if (prepared) {
    prepared.id = "activeSkinStylesheet";
    prepared.dataset.skinId = id;
    delete prepared.dataset.workspaceAppearance;
    prepared.media = "all";
    prepared = undefined;
  }
  setSkinIdentity(id); activeId.value = id;
  emit("changed");
}
async function syncFromServer(): Promise<void> {
  if (busy.value) { syncQueued = true; return; }
  if (props.recovery) { apply(""); return; }
  busy.value = true; error.value = "";
  controller = new AbortController(); const signal = controller.signal;
  try {
    const value = await request<SkinsPayload>("/api/v1/skins", { signal });
    if (!mounted || signal.aborted || props.recovery) return;
    const savedId = value.active_skin?.id ?? "";
    const id = workspaceSkinIsolated(savedId) ? "" : savedId;
    if (id) prepared = await prepareSkinStylesheet(value.active_skin!.stylesheet_url, signal);
    if (mounted && !signal.aborted && !props.recovery) apply(id);
  } catch (cause) { if (mounted && !signal.aborted) error.value = cause instanceof Error ? cause.message : "外观状态读取失败，请重试。"; }
  finally {
    prepared?.remove(); prepared = undefined; busy.value = false;
    if (syncQueued && mounted) { syncQueued = false; void syncFromServer(); }
  }
}
defineExpose({ syncFromServer });
watch(() => props.recovery, (recovery) => {
  if (recovery) { controller?.abort(); prepared?.remove(); prepared = undefined; apply(""); }
  else void syncFromServer();
});

onMounted(() => {
  if (props.recovery || workspaceSkinIsolated(activeId.value)) {
    document.getElementById("activeSkinStylesheet")?.remove();
    activeId.value = "";
  }
  setSkinIdentity(activeId.value);
});
onBeforeUnmount(() => {
  mounted = false;
  controller?.abort();
  prepared?.remove();
});

async function toggle(): Promise<void> {
  if (busy.value || props.recovery) return;
  busy.value = true;
  error.value = "";
  controller = new AbortController();
  const signal = controller.signal;
  const nextId = dark.value ? "" : DARK;
  let saving = false;
  try {
    if (nextId) {
      const catalog = await request<SkinsPayload>("/api/v1/skins", { signal });
      if (!mounted) return;
      const skin = catalog.skins.find((item) => item.id === nextId);
      if (!skin?.stylesheet_url) throw new Error("深色外观暂不可用，请刷新页面后重试。");
      // Load inactive CSS first. Saving or replacing the live link sooner would leave
      // a broken saved skin on failure; keeping the Vue tree preserves drafts/selections.
      prepared = await prepareSkinStylesheet(skin.stylesheet_url, signal);
    }
    if (!mounted || signal.aborted) return;
    saving = true;
    const result = await request<SkinsPayload>(nextId ? `/api/v1/skins/${nextId}/enable` : "/api/v1/skins/reset", {
      method: "POST", body: {}, signal,
    });
    if (!mounted || signal.aborted) return;
    if ((result.enabled_skin_id ?? "") !== nextId || (result.active_skin?.id ?? "") !== nextId) {
      throw new Error("外观保存结果未确认，请刷新页面核对。");
    }
    apply(nextId);
  } catch (cause) {
    if (mounted) {
      error.value = cause instanceof Error ? cause.message : "外观切换失败，请重试。";
      // A lost write response is not evidence that nothing was saved. Leave the live
      // appearance intact and ask for a read-back instead of replaying the POST.
      if (saving) error.value += " 请刷新页面核对保存状态。";
    }
  } finally {
    prepared?.remove();
    prepared = undefined;
    busy.value = false;
    if (syncQueued && mounted) { syncQueued = false; void syncFromServer(); }
  }
}
</script>

<template>
  <button class="rail-link appearance-toggle" type="button" :title="label" :aria-label="label"
    :aria-pressed="dark" :aria-busy="busy" :disabled="busy || recovery" @click="toggle">
    <span class="rail-icon" aria-hidden="true">{{ dark ? "☀" : "☾" }}</span>{{ dark ? "浅色" : "深色" }}
  </button>
  <div v-if="error" class="appearance-error banner banner--error" role="alert">
    <span>{{ error }}</span><button type="button" aria-label="关闭外观提示" @click="error = ''">×</button>
  </div>
</template>
