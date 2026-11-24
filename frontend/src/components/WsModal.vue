<script lang="ts">
// Nested dialogs (e.g. a confirm over the wizard) share one scroll lock.
let openCount = 0;
</script>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import WorkspaceIcon from "./WorkspaceIcon.vue";

// Prototype dialog (.modal-back / .modal): 640px (wide: 1100px), titled head with ×, body
// capped at 70vh. Esc and the × close; html+body scroll is locked while open (WEB_UI rule:
// locking only body leaks when a skin sets overflow-x on the root).
// `open` lets a host keep its content mounted (drafts survive) while the dialog is hidden.
const props = withDefaults(defineProps<{ title: string; subtitle?: string; wide?: boolean; closable?: boolean; open?: boolean; escape?: boolean }>(), { subtitle: "", wide: false, closable: true, open: true, escape: true });
// `escape: false` when the content handles Esc in layers itself (e.g. close a preview first).
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement>();
let restore: Element | null = null;

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape" && props.closable && props.escape) { event.preventDefault(); emit("close"); }
}
let locked = false;
function lock(on: boolean): void {
  if (on === locked) return;
  locked = on;
  openCount = Math.max(0, openCount + (on ? 1 : -1));
  document.documentElement.classList.toggle("ws-modal-open", openCount > 0);
}
async function show(): Promise<void> {
  restore = document.activeElement;
  lock(true);
  await nextTick();
  panel.value?.focus();
}
function hide(): void {
  lock(false);
  if (restore instanceof HTMLElement && restore.isConnected) restore.focus();
  restore = null;
}
watch(() => props.open, open => { if (open) void show(); else hide(); });
onMounted(() => { if (props.open) void show(); });
onBeforeUnmount(hide);
</script>

<template>
  <Teleport to="body">
    <div v-show="open" class="ws-modal-back" @keydown="onKey">
      <section ref="panel" class="ws-modal" :class="{ 'ws-modal--wide': wide }" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1">
        <header class="ws-modal__head">
          <div><h3>{{ title }}</h3><p v-if="subtitle">{{ subtitle }}</p></div>
          <slot name="head" />
          <button v-if="closable" type="button" class="ws-modal__x" aria-label="关闭" @click="emit('close')"><WorkspaceIcon name="x" /></button>
        </header>
        <div class="ws-modal__body"><slot /></div>
      </section>
    </div>
  </Teleport>
</template>
