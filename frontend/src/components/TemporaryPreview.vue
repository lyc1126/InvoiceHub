<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { request } from "../api/client";
import { errorText } from "../format";
import { TEMPORARY_API, type TemporaryFile } from "../temporary";

const props = defineProps<{ file: TemporaryFile; sessionId?: string; active: boolean }>();
const emit = defineEmits<{ back: [] }>();
const page = ref(1), pages = ref(0), type = ref("");
const text = ref(""), image = ref(""), error = ref("");
const loading = ref(false), zoom = ref("fit");
let generation = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
let controller: AbortController | undefined;
const path = (part = "") => `${TEMPORARY_API}/files/${encodeURIComponent(props.file.id)}/preview${part}${props.sessionId ? `?session_id=${encodeURIComponent(props.sessionId)}` : ""}`;
function clear(): void {
  text.value = "";
  if (image.value) URL.revokeObjectURL(image.value);
  image.value = "";
}
function stop(): void { ++generation; clearTimeout(timer); controller?.abort(); clear(); }
function fail(cause: unknown): void { clear(); error.value = errorText(cause); loading.value = false; }
async function verify(): Promise<void> {
  const turn = generation;
  try { await request(path()); }
  catch (cause) { if (turn === generation && props.active) fail(cause); return; }
  if (turn === generation && props.active) timer = setTimeout(verify, 3000);
}
async function load(): Promise<void> {
  stop();
  if (!props.active) return;
  const turn = generation;
  const current = () => turn === generation && props.active;
  const pending = new AbortController();
  controller = pending;
  const signal = pending.signal;
  loading.value = true; error.value = "";
  try {
    const meta = await request<{ name: string; type: string; pages: number; reason: string }>(path(), { signal });
    if (!current()) return;
    type.value = meta.type; pages.value = meta.pages;
    page.value = Math.min(page.value, Math.max(1, meta.pages));
    if (meta.type === "text") {
      const value = await request<{ text: string }>(path("/text"), { signal });
      if (current()) text.value = value.text;
    } else if (meta.type === "pages") {
      const timeout = setTimeout(() => pending.abort(), 15000);
      try {
        const response = await fetch(path(`/pages/${page.value}`), { signal, credentials: "same-origin", cache: "no-store" });
        if (!response.ok) {
          const value = await response.json().catch(() => null);
          throw new Error(typeof value?.detail === "string" ? value.detail : "原文件页面读取失败，请重新读取。");
        }
        const blob = await response.blob();
        if (current()) image.value = URL.createObjectURL(blob);
      } finally { clearTimeout(timeout); }
    } else throw new Error(meta.reason || "此文件暂不支持预览。");
    if (current()) timer = setTimeout(verify, 3000);
  } catch (cause) { if (current()) fail(cause); }
  finally { if (current()) loading.value = false; }
}
watch(() => `${props.file.id}/${props.sessionId ?? ""}`, () => { page.value = 1; void load(); });
watch(() => props.active, () => { if (props.active) void load(); else stop(); }, { immediate: true });
onBeforeUnmount(stop);
</script>

<template>
  <section class="temporary-preview panel" aria-label="临时原文件预览">
    <header class="page-header"><button type="button" @click="emit('back')">← 返回列表</button><h2>{{ file.name }}</h2></header>
    <div class="toolbar">
      <button type="button" aria-label="上一页" :disabled="loading || page <= 1" @click="page--; load()">←</button>
      <span>{{ type === "text" ? "XML 原文" : `${page} / ${pages} 页` }}</span>
      <button type="button" aria-label="下一页" :disabled="loading || page >= pages" @click="page++; load()">→</button>
      <label>显示 <select v-model="zoom" aria-label="临时预览缩放"><option value="fit">适应宽度</option><option value="large">放大</option></select></label>
    </div>
    <p v-if="error" role="alert" class="banner banner--error">{{ error }} <button type="button" @click="load">重新读取</button></p>
    <p v-if="loading" role="status">正在复核并读取原文件…</p>
    <div class="temporary-preview__content" :data-zoom="zoom" tabindex="0" aria-label="文件内容" :aria-busy="loading">
      <pre v-if="type === 'text' && !error && !loading">{{ text }}</pre>
      <img v-if="image" :src="image" :alt="`${file.name} 第 ${page} 页`" @error="fail(new Error('票面图片加载失败，请重新读取。'))">
    </div>
  </section>
</template>
