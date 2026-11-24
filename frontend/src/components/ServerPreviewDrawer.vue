<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { VIEW_ACTIVE } from "../modules";
import { ApiError, request } from "../api/client";
import { errorText } from "../format";
import type { ServerPreviewFile, ServerPreviewJob } from "../stores/sources";

// Source-bound multi-file preview drawer (WS-09). Mirrors SourcePreview's UX (100-file groups,
// thumbnails, keep-alive, Escape handling) while strictly using /api/v1/sources/{sid}/previews
// leases and releasing them on close, switch, or unmount.
const props = defineProps<{
  sourceId: string;
  entryIds: string[];
  label: string;
  allowStale: boolean;
}>();
const emit = defineEmits<{ close: [] }>();
const viewActive = inject(VIEW_ACTIVE, ref(true));

const THUMBNAIL_LIMIT = 12;
const FILE_WINDOW = 100;
const job = ref<ServerPreviewJob | null>(null);
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

const files = computed<ServerPreviewFile[]>(() => job.value?.files ?? []);
const file = computed<ServerPreviewFile | null>(() => files.value[fileIndex.value] ?? null);
const visibleFiles = computed(() =>
  files.value
    .slice(fileGroup.value * FILE_WINDOW, (fileGroup.value + 1) * FILE_WINDOW)
    .map((item, index) => ({ item, index: fileGroup.value * FILE_WINDOW + index })),
);
const pageUrl = (item: ServerPreviewFile, number: number) =>
  item.page_url_template.replace("{page_number}", String(number));
const thumbnails = computed(() => {
  const current = file.value;
  if (current?.preview_type !== "pages") return [];
  const start = Math.floor((page.value - 1) / THUMBNAIL_LIMIT) * THUMBNAIL_LIMIT + 1;
  return Array.from({ length: Math.min(THUMBNAIL_LIMIT, current.page_count - start + 1) }, (_, index) => ({
    page: start + index,
    url: pageUrl(current, start + index),
  }));
});

function cancelText(): void {
  textGeneration += 1;
  textController?.abort();
  textController = undefined;
  textLoading.value = false;
}

async function releaseCurrentJob(): Promise<void> {
  clearInterval(keepAlive);
  const current = job.value;
  job.value = null;
  if (current) {
    await request(`/api/v1/sources/${current.source_id}/previews/${current.job_id}`, { method: "DELETE" }).catch(() => undefined);
  }
}

async function createJob(): Promise<void> {
  const mine = ++generation;
  await releaseCurrentJob();
  if (mine !== generation) return;
  cancelText();
  loading.value = true;
  error.value = "";
  try {
    const created = await request<ServerPreviewJob>(`/api/v1/sources/${props.sourceId}/previews`, {
      method: "POST",
      body: { entry_ids: props.entryIds, allow_stale: props.allowStale },
    });
    if (mine !== generation) {
      await request(`/api/v1/sources/${props.sourceId}/previews/${created.job_id}`, { method: "DELETE" }).catch(() => undefined);
      return;
    }
    job.value = created;
    const total = created.files?.length ?? 0;
    fileIndex.value = Math.max(0, Math.min(fileIndex.value, Math.max(0, total - 1)));
    fileGroup.value = Math.floor(fileIndex.value / FILE_WINDOW);
    fileJump.value = fileIndex.value + 1;
    page.value = Math.max(1, Math.min(page.value, file.value?.page_count || 1));
    startKeepAlive();
    await loadText();
  } catch (cause) {
    if (mine !== generation) return;
    job.value = null;
    error.value =
      cause instanceof ApiError && cause.status === 409
        ? errorText(cause)
        : errorText(cause);
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
      if (textRebuilds++ === 0) await createJob();
      else error.value = "原文预览已失效，请关闭后重新打开。";
      return;
    }
    if (!response.ok) throw new Error(`原文读取失败（HTTP ${response.status}）。`);
    const content = await response.text();
    if (mine === textGeneration) text.value = content;
  } catch (cause) {
    if (mine === textGeneration) {
      error.value = controller.signal.aborted ? "原文读取超时，请重新打开预览。" : errorText(cause);
    }
  } finally {
    clearTimeout(timer);
    if (mine === textGeneration) textLoading.value = false;
  }
}

function startKeepAlive(): void {
  clearInterval(keepAlive);
  const url = job.value?.keep_alive_url;
  if (!url) return;
  const period = Math.max(30, Math.min(120, (job.value?.idle_timeout_seconds ?? 900) / 5)) * 1000;
  keepAlive = setInterval(async () => {
    if (!job.value || loading.value) return;
    const mine = generation;
    try {
      await request(url, { method: "POST", body: {} });
    } catch (cause) {
      if (mine !== generation) return;
      if (cause instanceof ApiError && (cause.status === 404 || cause.status === 410)) void createJob();
      else error.value = `预览续租失败：${errorText(cause)}`;
    }
  }, period);
}

function choose(index: number, number = 1): void {
  if (!Number.isInteger(index) || !files.value[index]) return;
  if (index !== fileIndex.value) {
    imageRebuilds = 0;
    textRebuilds = 0;
  }
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
    error.value = "这一页无法显示，可能来源文件已变化或授权过期，请关闭后重新预览。";
    return;
  }
  imageRebuilds += 1;
  void createJob();
}

watch(viewActive, (active) => {
  if (!active) emit("close");
});

watch(
  () => `${props.sourceId}:${props.allowStale}:${props.entryIds.join(",")}`,
  () => {
    fileIndex.value = 0;
    page.value = 1;
    imageRebuilds = 0;
    textRebuilds = 0;
    text.value = "";
    void createJob();
    void nextTick(() => closeButton.value?.focus());
  },
  { immediate: true },
);

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
  void releaseCurrentJob();
});
</script>

<template>
  <aside
    ref="panel"
    class="compare-drawer source-preview"
    role="dialog"
    aria-modal="false"
    :aria-label="`${label} 原票`"
    @keydown.escape.stop.prevent="emit('close')"
  >
    <header class="compare-drawer__head">
      <h3>服务器原票 · {{ label }}</h3>
      <button ref="closeButton" type="button" class="ws-tab__close" aria-label="关闭原票" @click="emit('close')">×</button>
    </header>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="loading && !job" class="muted" aria-busy="true">正在准备服务器原票…</p>
    <template v-if="job && file">
      <p class="muted" role="status">
        第 {{ fileIndex + 1 }} / {{ files.length }} 个源文件 · {{ file.name }}
        · {{ file.stale ? "离线副本（可能过期）" : "已校验副本" }} · 核验于 {{ file.verified_at }}
      </p>
      <template v-if="files.length > 1">
        <div class="source-preview__files" aria-label="源文件列表">
          <button
            v-for="{ item, index } in visibleFiles"
            :key="item.file_number"
            type="button"
            :class="{ primary: index === fileIndex }"
            :aria-pressed="index === fileIndex"
            @click="choose(index)"
          >{{ index + 1 }}. {{ item.name }}</button>
        </div>
        <form v-if="files.length > FILE_WINDOW" class="actions source-preview__jump" @submit.prevent="choose(Number(fileJump) - 1)">
          <button type="button" :disabled="fileGroup === 0" @click="fileGroup -= 1">上一组文件</button>
          <span class="muted">{{ fileGroup + 1 }} / {{ Math.ceil(files.length / FILE_WINDOW) }} 组</span>
          <button type="button" :disabled="(fileGroup + 1) * FILE_WINDOW >= files.length" @click="fileGroup += 1">下一组文件</button>
          <label>源文件序号 <input v-model="fileJump" type="number" min="1" :max="files.length" step="1" aria-label="源文件序号"></label>
          <button type="submit">跳转</button>
        </form>
      </template>
      <div v-if="thumbnails.length > 1" class="source-preview__thumbs" aria-label="缩略图">
        <button
          v-for="thumb in thumbnails"
          :key="`${fileIndex}-${thumb.page}`"
          type="button"
          :aria-label="`第 ${thumb.page} 页`"
          :class="{ 'is-active': thumb.page === page }"
          @click="choose(fileIndex, thumb.page)"
        >
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
