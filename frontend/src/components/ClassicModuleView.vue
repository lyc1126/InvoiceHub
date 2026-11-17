<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { frameLocation, MODULE_CHANNEL, type ModuleId, workspaceDestination } from "../modules";
import { useModulesStore } from "../stores/modules";

const props = defineProps<{ module: ModuleId; path: string; label: string; active: boolean; recovery: boolean }>();
const emit = defineEmits<{ navigate: [path: string]; appearance: []; stateChanged: [] }>();
const modules = useModulesStore();
const frame = ref<HTMLIFrameElement>();
const token = ref(crypto.randomUUID());
function sourceFor(path: string): string {
  const url = new URL(frameLocation(path, props.recovery), location.origin);
  url.searchParams.set("workspace_view", token.value);
  return `${url.pathname}${url.search}${url.hash}`;
}
const source = ref(sourceFor(modules.destinations[props.module] ?? props.path));
const loading = ref(true);
const error = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;
let mounted = true;
let handledShutdown = 0;
// The frame's own backdrop covers only the frame; the shell scrim covers the rest.
const modalOpen = ref(false);
const dimmed = computed(() => modalOpen.value && props.active);
watch(dimmed, value => { modules.modals[props.module] = value; });
function showShutdown(): void {
  if (props.module !== "settings" || !props.active || loading.value || handledShutdown === modules.shutdownRequests) return;
  handledShutdown = modules.shutdownRequests;
  send("shutdown-dialog");
}

function send(type: string): void {
  frame.value?.contentWindow?.postMessage({ channel: MODULE_CHANNEL, token: token.value, type, active: props.active, recovery: props.recovery }, location.origin);
}
function arm(): void {
  clearTimeout(timer);
  loading.value = true;
  modalOpen.value = false;
  error.value = "";
  timer = setTimeout(() => { loading.value = false; error.value = "模块未能完成加载，请重试或打开经典界面。"; }, 12000);
}
function reload(): void {
  arm();
  // A module may currently be on its own detail/skin page. Read its local URL,
  // never replay a write, and refresh only this module's current object.
  let destination = modules.destinations[props.module] ?? props.path;
  try {
    const current = frame.value?.contentWindow?.location;
    if (modules.destinations[props.module] && current?.origin === location.origin) {
      const desired = new URL(destination, location.origin), previous = new URL(current.href);
      for (const key of ["workspace_embed", "workspace_view"]) previous.searchParams.delete(key);
      if (desired.pathname === previous.pathname && desired.search === previous.search && desired.hash) {
        // Settings › About is a section change, not a reason to discard its drafts.
        current.hash = desired.hash; delete modules.destinations[props.module]; loading.value = false; clearTimeout(timer); return;
      }
    }
    if (!modules.destinations[props.module] && current?.origin === location.origin) destination = `${current.pathname}${current.search}${current.hash}`;
  } catch { /* An unexpected origin is reset to this module's fixed entry. */ }
  try { frameLocation(destination, props.recovery); } catch { destination = props.path; }
  // Refresh replaces this browsing context and its history. Normal rail switches
  // keep it attached; a refresh must not revive a previous document/view token.
  token.value = crypto.randomUUID();
  const next = sourceFor(destination);
  if (next === source.value && frame.value) frame.value.src = next;
  else source.value = next;
}
function receive(event: MessageEvent): void {
  const source = frame.value?.contentWindow;
  if (!mounted || !source || event.origin !== location.origin || event.source !== source || event.data?.channel !== MODULE_CHANNEL || event.data.token !== token.value) return;
  if (event.data.type === "ready") {
    clearTimeout(timer); delete modules.destinations[props.module]; loading.value = false; error.value = ""; send("activity"); send("appearance"); showShutdown();
  } else if (event.data.type === "navigate" && props.active && typeof event.data.href === "string") {
    const destination = workspaceDestination(event.data.href);
    if (destination !== null) emit("navigate", destination);
  } else if (event.data.type === "appearance-changed") emit("appearance");
  else if (event.data.type === "state-changed") emit("stateChanged");
  else if (event.data.type === "modal" && typeof event.data.open === "boolean") modalOpen.value = event.data.open;
  else if (event.data.type === "notice" && typeof event.data.message === "string") error.value = event.data.message;
}
function syncAppearance(): void { send("appearance"); }
watch(() => props.active, () => { send("activity"); showShutdown(); });
watch(() => modules.shutdownRequests, showShutdown);
watch(() => props.recovery, () => send("appearance"));
watch(() => modules.refresh[props.module] ?? 0, reload);
onMounted(() => { arm(); window.addEventListener("message", receive); window.addEventListener("workspace:appearance-sync", syncAppearance); });
onBeforeUnmount(() => { mounted = false; modules.modals[props.module] = false; clearTimeout(timer); window.removeEventListener("message", receive); window.removeEventListener("workspace:appearance-sync", syncAppearance); });
</script>

<template>
  <section class="module-view" :aria-label="`${label}模块`">
    <p v-if="loading" class="module-status muted" role="status">正在打开{{ label }}…</p>
    <div v-if="error" class="banner banner--error" role="alert">
      {{ error }} <button type="button" @click="reload">重新加载</button> <a :href="recovery ? `${path}?no_skin=1` : path">打开经典界面</a>
    </div>
    <!-- These documents stay attached with v-show at the App level. KeepAlive's
         detached DOM would destroy iframe browsing contexts and lose page drafts. -->
    <iframe :key="token" ref="frame" class="module-frame" :class="{ 'module-frame--modal': dimmed }" :src="source" :title="label" allow="clipboard-write" :aria-hidden="!active" :tabindex="active ? 0 : -1" @load="modalOpen = false; send('activity')" />
  </section>
</template>
