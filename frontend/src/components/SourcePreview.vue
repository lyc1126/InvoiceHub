<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { PreviewRef } from "../api/types";
import { errorText } from "../format";

// Directory selections and compare records share the homepage preview pipeline. Every source
// format is preserved; preview-jobs re-validates target_id + invoice_key + source_path. Jobs
// stay alive only while this panel is mounted, and recovery keeps the selected file/page.
interface PreviewFile {
  file_number: number; name: string; preview_type: string; page_count: number;
  reason: string; page_url_template: string; text_url: string;
}
interface PreviewJob { job_id: string; keep_alive_url: string; idle_timeout_seconds: number; files: PreviewFile[] }

const props = defineProps<{ label: string; preview: PreviewRef }>();
const emit = defineEmits<{ close: [] }>();
const THUMBNAIL_LIMIT = 12;
const FILE_WINDOW = 100;
const job = ref<PreviewJob | null>(null);
const error = ref("");
const loading = ref(false);
const fileIndex = ref(0);
const fileGroup = ref(0);
const fileJump = ref(1);
const page = ref(1);
const text = ref("");
const textLoading = ref(false);
const closeButton = ref<HTMLButtonElement | null>(null);
const panel = ref<HTMLElement | null>(null);
let generation = 0;
let textGeneration = 0;
let imageRebuilds = 0;
let textRebuilds = 0;
let textController: AbortController | undefined;
let keepAlive: ReturnType<typeof setInterval> | undefined;

const file = computed(() => job.value?.files[fileIndex.value] ?? null);
const visibleFiles = computed(() => (job.value?.files ?? []).slice(fileGroup.value * FILE_WINDOW, (fileGroup.value + 1) * FILE_WINDOW)
  .map((item, index) => ({ item, index: fileGroup.value * FILE_WINDOW + index })));
const pageUrl = (item: PreviewFile, number: number) => item.page_url_template.replace("{page_number}", String(number));
const thumbnails = computed(() => {
  const current = file.value;
  if (current?.preview_type !== "pages") return [];
  const start = Math.floor((page.value - 1) / THUMBNAIL_LIMIT) * THUMBNAIL_LIMIT + 1;
  return Array.from({ length: Math.min(THUMBNAIL_LIMIT, current.page_count - start + 1) }, (_, index) =>
    ({ page: start + index, url: pageUrl(current, start + index) }));
});

function cancelText(): void {
  textGeneration += 1;
  textController?.abort();
  textController = undefined;
  textLoading.value = false;
}

async function createJob(): Promise<void> {
  const mine = ++generation;
  clearInterval(keepAlive);
  cancelText();
  loading.value = true;
  error.value = "";
  try {
    const created = await request<PreviewJob>("/api/v1/invoices/preview-jobs", { method: "POST", body: props.preview, timeoutMs: 60_000 });
    if (mine !== generation) return;
    job.value = created;
    fileIndex.value = Math.max(0, Math.min(fileIndex.value, created.files.length - 1));
    fileGroup.value = Math.floor(fileIndex.value / FILE_WINDOW);
    fileJump.value = fileIndex.value + 1;
    page.value = Math.max(1, Math.min(page.value, file.value?.page_count || 1));
    startKeepAlive();
    await loadText();
  } catch (cause) {
    if (mine !== generation) return;
    job.value = null;
    error.value = cause instanceof ApiError && cause.status === 409 ? "发票或监控目录已变化，请刷新列表、重新勾选后再预览。" : errorText(cause);
  } finally {
    if (mine === generation) loading.value = false;
  }
}

async function loadText(): Promise<void> {
  cancelText();
  text.value = "";
  const current = file.value;
  if (!current || current.preview_type !== "text") return;
  const mine = textGeneration;
  const controller = new AbortController();
  textController = controller;
  textLoading.value = true;
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(current.text_url, { credentials: "same-origin", signal: controller.signal });
    if (mine !== textGeneration) return;
    if (response.status === 404 || response.status === 410) {
      // Only one immediate XML recovery: a persistently missing text URL must not loop.
      if (textRebuilds++ === 0) await createJob();
      else error.value = "原文预览已失效，请关闭后重新打开。";
      return;
    }
    if (!response.ok) throw new Error(`原文读取失败（HTTP ${response.status}）。`);
    const content = await response.text();
    // Reading the body is asynchronous too: a slow previous XML must not replace a new file.
    if (mine === textGeneration) text.value = content;
  } catch (cause) {
    if (mine === textGeneration) error.value = controller.signal.aborted ? "原文读取超时，请重新打开预览。" : errorText(cause);
  } finally {
    clearTimeout(timer);
    if (mine === textGeneration) textLoading.value = false;
  }
}

function startKeepAlive(): void {
  clearInterval(keepAlive);
  const period = Math.max(30, Math.min(120, (job.value?.idle_timeout_seconds ?? 900) / 5)) * 1000;
  keepAlive = setInterval(async () => {
    if (!job.value || loading.value) return;
    const mine = generation;
    try {
      await request(job.value.keep_alive_url, { method: "POST" });
    } catch (cause) {
      if (mine !== generation) return;
      if (cause instanceof ApiError && (cause.status === 404 || cause.status === 410)) void createJob();
      else error.value = `预览续租失败：${errorText(cause)}`;
    }
  }, period);
}

function choose(index: number, number = 1): void {
  if (!Number.isInteger(index) || !job.value?.files[index]) return;
  if (index !== fileIndex.value) { imageRebuilds = 0; textRebuilds = 0; }
  fileIndex.value = index;
  fileGroup.value = Math.floor(index / FILE_WINDOW);
  fileJump.value = index + 1;
  page.value = number;
  error.value = "";
  void loadText();
}

function onImageError(): void {
  if (loading.value) return;
  if (imageRebuilds >= 1) {
    error.value = "这一页无法显示，请关闭后重新预览，或到经典首页核对原票。";
    return;
  }
  imageRebuilds += 1;
  void createJob();
}

watch(() => JSON.stringify(props.preview), () => {
  fileIndex.value = 0;
  page.value = 1;
  imageRebuilds = 0;
  textRebuilds = 0;
  job.value = null;
  text.value = "";
  void createJob();
  void nextTick(() => closeButton.value?.focus());
}, { immediate: true });

// A last-page button becomes disabled and can drop focus to body. Handle Escape for
// the visible panel only: cached, hidden workspace tabs must not consume this key.
function onEscape(event: KeyboardEvent): void {
  if (event.key === "Escape" && panel.value?.getClientRects().length) {
    event.preventDefault();
    emit("close");
  }
}

onMounted(() => window.addEventListener("keydown", onEscape));
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onEscape);
  generation += 1;
  cancelText();
  clearInterval(keepAlive);
});
</script>

<template>
  <aside ref="panel" class="compare-drawer source-preview" role="dialog" aria-modal="false" :aria-label="`${label} 原票`" @keydown.escape.stop.prevent="emit('close')">
    <header class="compare-drawer__head">
      <h3>原票 · {{ label }}</h3>
      <button ref="closeButton" type="button" class="ws-tab__close" aria-label="关闭原票" @click="emit('close')">×</button>
    </header>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="loading && !job" class="muted" aria-busy="true">正在准备原票…</p>
    <template v-if="job && file">
      <p class="muted">第 {{ fileIndex + 1 }} / {{ job.files.length }} 个源文件 · {{ file.name }}</p>
      <template v-if="job.files.length > 1">
        <div class="source-preview__files" aria-label="源文件列表">
          <button v-for="{ item, index } in visibleFiles" :key="item.file_number" type="button" :class="{ primary: index === fileIndex }" :aria-pressed="index === fileIndex" @click="choose(index)">{{ index + 1 }}. {{ item.name }}</button>
        </div>
        <form class="actions source-preview__jump" @submit.prevent="choose(Number(fileJump) - 1)">
          <button type="button" :disabled="fileGroup === 0" @click="fileGroup -= 1">上一组文件</button>
          <span class="muted">{{ fileGroup + 1 }} / {{ Math.ceil(job.files.length / FILE_WINDOW) }} 组</span>
          <button type="button" :disabled="(fileGroup + 1) * FILE_WINDOW >= job.files.length" @click="fileGroup += 1">下一组文件</button>
          <label>源文件序号 <input v-model="fileJump" type="number" min="1" :max="job.files.length" step="1" aria-label="源文件序号"></label>
          <button type="submit">跳转</button>
        </form>
      </template>
      <div v-if="thumbnails.length > 1" class="source-preview__thumbs" aria-label="缩略图">
        <button v-for="thumb in thumbnails" :key="`${fileIndex}-${thumb.page}`" type="button" :aria-label="`第 ${thumb.page} 页`" :class="{ 'is-active': thumb.page === page }" @click="choose(fileIndex, thumb.page)">
          <img :src="thumb.url" alt="" loading="lazy" @error="onImageError">
        </button>
      </div>
      <template v-if="file.preview_type === 'pages'">
        <img class="source-preview__page" :src="pageUrl(file, page)" :alt="`${file.name} 第 ${page} 页`" @error="onImageError">
        <div v-if="file.page_count > 1" class="actions">
          <button type="button" :disabled="page <= 1" @click="choose(fileIndex, page - 1)">上一页</button>
          <span class="muted">{{ page }} / {{ file.page_count }}</span>
          <button type="button" :disabled="page >= file.page_count" @click="choose(fileIndex, page + 1)">下一页</button>
        </div>
      </template>
      <pre v-else-if="file.preview_type === 'text'" class="source-preview__text">{{ textLoading ? "正在读取…" : text || "原文为空。" }}</pre>
      <p v-else class="muted">{{ file.reason || "这个文件不能在页面里预览。" }}</p>
    </template>
  </aside>
</template>
