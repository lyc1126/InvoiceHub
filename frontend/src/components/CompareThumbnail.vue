<script setup lang="ts">
import { inject, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import { createPreviewJob, type PreviewJob } from "../api/preview";
import type { CompareRecord } from "../api/types";
import { VIEW_ACTIVE } from "../modules";
import { errorText } from "../format";

const props = defineProps<{ record: CompareRecord }>();
defineEmits<{ open: [] }>();
const active = inject(VIEW_ACTIVE, ref(true));
const url = ref("");
const message = ref("");
const loading = ref(false);
let generation = 0;
let controller: AbortController | undefined;
let heartbeat: ReturnType<typeof setInterval> | undefined;
let recovered = false;
function stop(): void { generation += 1; controller?.abort(); clearInterval(heartbeat); url.value = ""; loading.value = false; }
async function load(): Promise<void> {
  stop();
  if (!active.value || !props.record.preview) return;
  const mine = generation;
  controller = new AbortController();
  loading.value = true;
  message.value = "";
  try {
    const job = await createPreviewJob(props.record.preview, controller.signal);
    if (mine !== generation) return;
    const file = job.files.find((item) => item.preview_type === "pages") ?? job.files[0];
    if (file?.preview_type === "pages") url.value = file.page_url_template.replace("{page_number}", String(job.initial_page ?? 1));
    else message.value = file?.preview_type === "text" ? "XML 原文" : file?.reason || "暂无票面";
    heartbeat = setInterval(() => void renew(job, mine), 120_000);
  } catch (cause) { if (mine === generation) message.value = errorText(cause); }
  finally { if (mine === generation) loading.value = false; }
}
async function renew(job: PreviewJob, mine: number): Promise<void> {
  try { await request(job.keep_alive_url, { method: "POST" }); }
  catch (cause) {
    if (mine !== generation) return;
    if (cause instanceof ApiError && [404, 410].includes(cause.status) && !recovered) { recovered = true; void load(); }
    else { stop(); message.value = errorText(cause); }
  }
}
function imageError(): void {
  if (!recovered) { recovered = true; void load(); }
  else { stop(); message.value = "缩略图暂不可用，点击查看原票。"; }
}
watch(() => `${active.value}/${JSON.stringify(props.record.preview)}`, () => { recovered = false; void load(); }, { immediate: true });
onBeforeUnmount(stop);
</script>

<template>
  <button type="button" class="compare-thumbnail" :aria-label="`查看原票 ${record.invoice_number || record.source_file}`" :aria-busy="loading" @click="$emit('open')">
    <img v-if="url" :src="url" alt="" @error="imageError">
    <span v-else class="muted">{{ loading ? "正在准备…" : message || "暂无票面" }}</span>
  </button>
</template>
