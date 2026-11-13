<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { PreviewRef } from "../api/types";
import { errorText } from "../format";

// Original invoice of a compare record (WS-04), through the homepage's preview pipeline: the
// backend attached `invoice_key + source_path` only to the monitored folder's records, and
// preview-jobs re-validates them against the current watch_dir. The job is kept alive while the
// panel is open and rebuilt (same file and page) when it expired or the backend restarted.
interface PreviewFile {
  file_number: number; name: string; preview_type: "pages" | "text" | string; page_count: number;
  reason: string; page_url_template: string; text_url: string;
}
interface PreviewJob { job_id: string; keep_alive_url: string; idle_timeout_seconds: number; files: PreviewFile[] }

const props = defineProps<{ label: string; preview: PreviewRef }>();
const emit = defineEmits<{ close: [] }>();
const THUMBNAIL_LIMIT = 12;
const job = ref<PreviewJob | null>(null);
const error = ref("");
const loading = ref(false);
const fileIndex = ref(0);
const page = ref(1);
const text = ref("");
const closeButton = ref<HTMLButtonElement | null>(null);
let generation = 0;
// One rebuild per opened record for a failing page image; a page that cannot render must not loop.
let imageRebuilds = 0;
let keepAlive: ReturnType<typeof setInterval> | undefined;

const file = computed(() => job.value?.files[fileIndex.value] ?? null);
const pageUrl = (item: PreviewFile, number: number) => item.page_url_template.replace("{page_number}", String(number));
// Small first pages of every file, then the rest, capped so a long PDF does not render everything.
const thumbnails = computed(() => {
  const out: { fileIndex: number; page: number; url: string }[] = [];
  (job.value?.files ?? []).forEach((item, index) => {
    for (let number = 1; item.preview_type === "pages" && number <= item.page_count && out.length < THUMBNAIL_LIMIT; number += 1) {
      out.push({ fileIndex: index, page: number, url: pageUrl(item, number) });
    }
  });
  return out;
});

async function createJob(): Promise<void> {
  const mine = ++generation;
  loading.value = true;
  error.value = "";
  try {
    // Rendering an OFD can take a while; the homepage allows the same.
    const created = await request<PreviewJob>("/api/v1/invoices/preview-jobs", { method: "POST", body: props.preview, timeoutMs: 60_000 });
    if (mine !== generation) return; // closed or replaced meanwhile
    job.value = created;
    fileIndex.value = Math.min(fileIndex.value, created.files.length - 1);
    startKeepAlive();
    await loadText();
  } catch (cause) {
    if (mine !== generation) return;
    job.value = null;
    error.value = cause instanceof ApiError && cause.status === 409 ? "这张发票在监控目录里已变化，请重新核对后再看原票。" : errorText(cause);
  } finally {
    if (mine === generation) loading.value = false;
  }
}

async function loadText(): Promise<void> {
  text.value = "";
  const current = file.value;
  if (!current || current.preview_type !== "text") return;
  const mine = generation;
  const response = await fetch(current.text_url, { credentials: "same-origin" });
  if (mine !== generation || file.value !== current) return;
  if (response.status === 404 || response.status === 410) return void createJob();
  text.value = response.ok ? await response.text() : "原文读取失败。";
}

function startKeepAlive(): void {
  clearInterval(keepAlive);
  const period = Math.max(30, Math.min(120, (job.value?.idle_timeout_seconds ?? 900) / 5)) * 1000;
  keepAlive = setInterval(async () => {
    if (!job.value) return;
    try {
      await request(job.value.keep_alive_url, { method: "POST" });
    } catch (cause) {
      // Expired (410) or unknown after a restart (404): rebuild the same view.
      if (cause instanceof ApiError && (cause.status === 404 || cause.status === 410)) void createJob();
    }
  }, period);
}

function choose(index: number, number = 1): void {
  fileIndex.value = index;
  page.value = number;
  void loadText();
}

function onImageError(): void {
  // Usually a page URL of an expired job: rebuild once, keeping the current file and page.
  if (loading.value) return;
  if (imageRebuilds >= 1) {
    error.value = "这一页无法显示，可在经典首页预览原票。";
    return;
  }
  imageRebuilds += 1;
  void createJob();
}

watch(() => JSON.stringify(props.preview), () => {
  fileIndex.value = 0;
  page.value = 1;
  imageRebuilds = 0;
  void createJob();
  void nextTick(() => closeButton.value?.focus());
}, { immediate: true });

onBeforeUnmount(() => {
  generation += 1;
  clearInterval(keepAlive);
});
</script>

<template>
  <aside class="compare-drawer source-preview" role="dialog" aria-modal="false" :aria-label="`${label} 原票`" @keydown.escape="emit('close')">
    <header class="compare-drawer__head">
      <h3>原票 · {{ label }}</h3>
      <button ref="closeButton" type="button" class="ws-tab__close" aria-label="关闭原票" @click="emit('close')">×</button>
    </header>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="loading && !job" class="muted" aria-busy="true">正在准备原票…</p>
    <template v-if="job && file">
      <div v-if="job.files.length > 1" class="toolbar">
        <button v-for="(item, index) in job.files" :key="item.file_number" type="button" :class="{ primary: index === fileIndex }" @click="choose(index)">{{ item.name }}</button>
      </div>
      <p v-else class="muted">{{ file.name }}</p>
      <div v-if="thumbnails.length > 1" class="source-preview__thumbs" aria-label="缩略图">
        <button
          v-for="thumb in thumbnails"
          :key="`${thumb.fileIndex}-${thumb.page}`"
          type="button"
          :aria-label="`第 ${thumb.page} 页`"
          :class="{ 'is-active': thumb.fileIndex === fileIndex && thumb.page === page }"
          @click="choose(thumb.fileIndex, thumb.page)"
        >
          <img :src="thumb.url" alt="" loading="lazy" @error="onImageError">
        </button>
      </div>
      <template v-if="file.preview_type === 'pages'">
        <img class="source-preview__page" :src="pageUrl(file, page)" :alt="`${file.name} 第 ${page} 页`" @error="onImageError">
        <div v-if="file.page_count > 1" class="actions">
          <button type="button" :disabled="page <= 1" @click="page -= 1">上一页</button>
          <span class="muted">{{ page }} / {{ file.page_count }}</span>
          <button type="button" :disabled="page >= file.page_count" @click="page += 1">下一页</button>
        </div>
      </template>
      <pre v-else-if="file.preview_type === 'text'" class="source-preview__text">{{ text || "正在读取…" }}</pre>
      <p v-else class="muted">{{ file.reason || "这个文件不能在页面里预览。" }}</p>
    </template>
  </aside>
</template>
