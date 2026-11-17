<script setup lang="ts">
import WorkspaceIcon from "../components/WorkspaceIcon.vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRef, watch } from "vue";
import TemporaryPreview from "../components/TemporaryPreview.vue";
import { TEMPORARY_COLUMNS, temporaryCell, useTemporaryRecognition, type TemporaryFile } from "../temporary";

const props = defineProps<{ active: boolean; refresh: number }>();
const emit = defineEmits<{ exit: [] }>();
const state = useTemporaryRecognition(toRef(props, "active"));
const { files, view, settings, settingsDraft, settingsDirty, sessions, running, selected, result, busy, loading, message } = state;
const preview = ref<{ file: TemporaryFile; sessionId?: string } | null>(null);
const rename = ref<{ id: string; title: string } | null>(null);
const deleteId = ref<string | null>(null);
const settingsOpen = ref(false);
const queue = ref<HTMLOListElement>();
const progress = computed(() => sessions.value.find((session) => session.id === running.value));
let drag: { from: number; to: number; pointer: number; button: HTMLElement } | null = null;
const date = (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false });

async function move(from: number, to: number): Promise<void> {
  state.move(from, to);
  await nextTick();
  queue.value?.children[to]?.querySelector<HTMLButtonElement>("button")?.focus();
}
function dragStart(event: PointerEvent, from: number): void {
  if (busy.value || running.value) return;
  const button = event.currentTarget as HTMLElement;
  button.setPointerCapture(event.pointerId);
  drag = { from, to: from, pointer: event.pointerId, button };
}
function dragMove(event: PointerEvent): void {
  if (!drag) return;
  const row = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>("[data-file-index]");
  if (row && queue.value?.contains(row)) drag.to = Number(row.dataset.fileIndex);
}
function dragEnd(cancel = false): void {
  if (!drag) return;
  const current = drag; drag = null;
  if (current.button.hasPointerCapture?.(current.pointer)) current.button.releasePointerCapture(current.pointer);
  if (!cancel) void move(current.from, current.to);
}
function browserDrop(event: DragEvent): void {
  if (!props.active || !event.dataTransfer?.files.length || busy.value || running.value) return;
  message.value = "浏览器需要确认源文件位置，请在原生选择器中选择刚才拖入的文件。";
  void state.pick();
}
function nativeDrop(event: Event): void {
  if (!props.active || preview.value || view.value !== "draft") return;
  const paths: unknown = (event as CustomEvent).detail;
  if (Array.isArray(paths) && paths.length > 0 && paths.length <= 50 && paths.every((path) => typeof path === "string")) void state.pick(paths);
}
function escape(event: KeyboardEvent): void {
  if (!props.active || event.key !== "Escape") return;
  if (preview.value) preview.value = null;
  else if (rename.value) rename.value = null;
  else emit("exit");
  event.preventDefault();
}
function switchView(next: "draft" | "history"): void { preview.value = null; rename.value = null; deleteId.value = null; state.switchView(next); }
async function saveName(): Promise<void> {
  if (!rename.value) return;
  const item = rename.value;
  if (await state.rename(item.id, item.title) && rename.value === item) rename.value = null;
}
watch(() => props.refresh, () => { preview.value = null; rename.value = null; deleteId.value = null; state.refresh(); });
watch(() => props.active, (active) => { if (!active) dragEnd(true); });
onMounted(() => { window.addEventListener("invoicehub:temporary-drop", nativeDrop); window.addEventListener("keydown", escape); });
onBeforeUnmount(() => { dragEnd(true); window.removeEventListener("invoicehub:temporary-drop", nativeDrop); window.removeEventListener("keydown", escape); });
</script>

<template>
  <section class="temporary-workspace" aria-label="临时识别工作区">
    <!-- Shown inside the shell dialog (title / × come from WsModal); the route stays for drag-in. -->
    <p class="overview-notice"><span>只处理所选 PDF / OFD / XML，原文件保留在原位置，<b>不写入任何公司档案</b>、普通汇总或成本分析。</span></p>
    <nav class="temporary-nav" aria-label="临时识别视图">
      <span class="period-segment">
        <button type="button" :aria-pressed="view === 'draft' && !preview" :disabled="busy" @click="switchView('draft')">新建识别</button>
        <button type="button" :aria-pressed="view === 'history' && !preview" :disabled="busy" @click="switchView('history')">查看历史 {{ sessions.length || "" }}</button>
      </span>
      <button type="button" class="ghost" :aria-expanded="settingsOpen" @click="settingsOpen = !settingsOpen">临时识别设置</button>
    </nav>
    <form v-if="settingsOpen" class="panel" aria-label="临时识别设置" @submit.prevent="state.saveSettings">
      <div class="field-row"><label>每批上限 <input v-model.number="settingsDraft.batch_limit" aria-label="每批文件上限" type="number" min="1" max="50" required :disabled="busy" @input="settingsDirty = true"></label>
        <label><input v-model="settingsDraft.auto_open" type="checkbox" :disabled="busy" @change="settingsDirty = true">完成后自动打开结果</label>
        <button type="submit" :disabled="busy || !settingsDirty" :aria-busy="busy">保存设置</button></div>
    </form>
    <p v-if="message" class="banner banner--note" role="status">{{ message }}</p>
    <TemporaryPreview v-if="preview" :file="preview.file" :session-id="preview.sessionId" :active="active" @back="preview = null" />
    <section v-else-if="view === 'draft'" class="panel" aria-label="临时识别队列" @dragover.prevent @drop.prevent="browserDrop">
      <button class="temporary-dropzone" type="button" :disabled="busy || !!running" :aria-busy="busy" @click="state.pick()"><WorkspaceIcon name="upload" /><strong>拖入发票 PDF / OFD / XML</strong><span>或点击选择文件 · 单个文件 ≤ 32 MB · 图片及纯扫描件暂不支持</span></button>
      <p class="muted">{{ files.length }} 个文件 · 上限 {{ settings.batch_limit }} 个。拖动手柄或用上移、下移按钮排序。</p>
      <ol ref="queue" class="temporary-queue" aria-label="文件识别顺序">
        <li v-for="(file, index) in files" :key="file.id" :data-file-index="index" class="temporary-queue__row">
          <button type="button" class="temporary-handle" :aria-label="`排序 ${file.name}`" :disabled="busy || !!running" @pointerdown="dragStart($event, index)" @pointermove="dragMove" @pointerup="dragEnd()" @pointercancel="dragEnd(true)" @keydown.up.prevent="move(index, index - 1)" @keydown.down.prevent="move(index, index + 1)">⠿</button>
          <span class="temporary-file-name">{{ index + 1 }}. {{ file.name }} <small class="muted">{{ ((file.size ?? 0) / 1024).toFixed(1) }} KB</small></span>
          <div class="actions"><button type="button" :aria-label="`预览 ${file.name}`" :disabled="busy" @click="preview = { file }">预览</button>
            <button type="button" :aria-label="`上移 ${file.name}`" :disabled="busy || !!running || index === 0" @click="move(index, index - 1)">↑</button>
            <button type="button" :aria-label="`下移 ${file.name}`" :disabled="busy || !!running || index === files.length - 1" @click="move(index, index + 1)">↓</button>
            <button type="button" :aria-label="`移除 ${file.name}`" :disabled="busy || !!running" @click="files.splice(index, 1)">×</button></div>
        </li>
      </ol>
      <div v-if="running" class="temporary-progress" role="status"><span>正在后台识别 {{ progress?.completed ?? 0 }} / {{ progress?.count ?? files.length }}</span><progress :value="progress?.completed ?? 0" :max="progress?.count || files.length || 1" aria-label="临时识别进度" /></div>
      <div class="actions"><button type="button" class="primary" :disabled="busy || !!running || !files.length" :aria-busy="busy" @click="state.start">{{ running ? "识别中…" : "识别" }}</button><button v-if="selected" type="button" :disabled="busy" @click="state.show(selected)">查看本次识别结果</button></div>
    </section>
    <section v-else-if="view === 'history'" aria-label="临时识别历史">
      <p class="muted">任一原文件移动、删除或变化后，旧线程明细不可查看。删除记录只删除缓存。</p>
      <p v-if="loading" role="status">正在读取历史…</p><p v-else-if="!sessions.length" class="muted">还没有临时识别记录。</p>
      <article v-for="session in sessions" :key="session.id" class="panel temporary-history-row">
        <button type="button" class="link temporary-history-open" @click="state.show(session.id)"><strong>{{ session.title }}</strong><small>{{ session.count }} 个文件 · {{ session.unavailable.length ? '源文件不可用' : session.status === 'running' ? '识别中' : session.status === 'interrupted' ? '识别中断' : '识别完成' }}</small></button>
        <time>{{ date(session.created_at) }}</time>
        <div class="actions"><button type="button" :disabled="busy || session.status === 'running'" @click="rename = { id: session.id, title: session.title }">重命名</button><button type="button" :disabled="busy || session.status === 'running'" @click="deleteId = session.id">删除记录</button></div>
        <form v-if="rename?.id === session.id" class="field-row" @submit.prevent="saveName"><input v-model="rename.title" aria-label="识别记录名称" maxlength="160" required :disabled="busy"><button type="submit" :disabled="busy">保存名称</button><button type="button" :disabled="busy" @click="rename = null">取消</button></form>
        <div v-if="deleteId === session.id" class="actions" role="alertdialog" aria-label="删除识别记录确认"><span>只删除缓存记录，原文件保留。</span><button type="button" :disabled="busy" @click="state.remove(session.id).then(() => deleteId = null)">确认删除记录</button><button type="button" :disabled="busy" @click="deleteId = null">取消删除</button></div>
      </article>
    </section>
    <section v-else aria-label="临时识别结果">
      <p v-if="loading" role="status">正在检查原文件…</p>
      <div v-if="result" class="panel"><div class="page-header"><div><h2>{{ result.title }}</h2><p class="muted">{{ date(result.created_at) }} · 已处理 {{ result.completed }} / {{ result.count }}</p></div><button type="button" :disabled="busy || result.status !== 'ready'" :aria-busy="busy" @click="state.copy">复制表格</button></div>
        <div class="temporary-table-scroll"><table class="grid"><thead><tr><th v-for="[key, label] in TEMPORARY_COLUMNS" :key="key">{{ label }}</th><th>操作</th></tr></thead><tbody><tr v-for="item in result.items" :key="item.id"><td v-for="[key] in TEMPORARY_COLUMNS" :key="key">{{ temporaryCell(item, key) || '—' }}</td><td><button type="button" :disabled="item.status === 'pending'" :aria-label="`预览 ${item.name}`" @click="preview = { file: item, sessionId: result.id }">预览</button></td></tr></tbody></table></div>
      </div>
    </section>
  </section>
</template>
