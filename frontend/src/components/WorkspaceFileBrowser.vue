<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { request } from "../api/client";
import type {
  Company,
  DirectoryFileEntry,
  DirectoryFilesPayload,
  FileImportPreviewPayload,
  FileMovePlanPayload,
  FileRenameResult,
  FileTrashConfirmPayload,
  FileTrashPreviewPayload,
  FileUploadResult,
} from "../api/types";
import { errorText } from "../format";
import { companySourceKey, useCompaniesStore } from "../stores/companies";
import { toast } from "../toast";
import FileMoveModal from "./FileMoveModal.vue";
import WsModal from "./WsModal.vue";

// Universal workspace file browser & drag-and-drop uploader (WS-12).
// Serves non-invoice directories directly and is available alongside invoice lists for
// subfolder navigation and non-overwriting file import. Existing-file mutations strictly
// follow backend `can_mutate_existing` (honoring BOOKKEEPING.md read-only non-monitored rules).
const props = defineProps<{
  company: Company;
  dirKey: string;
  isInvoiceDir?: boolean;
}>();
const emit = defineEmits<{ mutated: [] }>();
const companies = useCompaniesStore();

const subpath = ref("");
const q = ref("");
const extFilter = ref("");
const sortBy = ref<"name" | "mtime" | "size">("name");
const sortDir = ref<"asc" | "desc">("asc");
const loading = ref(false);
const error = ref("");
const data = ref<DirectoryFilesPayload | null>(null);

// Subfolder creation
const mkdirOpen = ref(false);
const mkdirName = ref("");
const mkdirBusy = ref(false);

// Drag-drop / picker upload
const dragOver = ref(false);
const fileInputRef = ref<HTMLInputElement | null>(null);
const stagedFiles = ref<File[]>([]);
const uploadConflictPolicy = ref<"rename" | "skip">("rename");
const importPreview = ref<FileImportPreviewPayload | null>(null);
const uploading = ref(false);
const uploadProgress = ref("");
const uploadResults = ref<FileUploadResult[]>([]);

// Single-file rename
const renameTarget = ref<DirectoryFileEntry | null>(null);
const renameValue = ref("");
const renameBusy = ref(false);
const renameError = ref("");

// Cross-dir move
const movePaths = ref<string[] | null>(null);

// Native recycle-bin delete
const trashPreview = ref<FileTrashPreviewPayload | null>(null);
const trashConfirmed = ref(false);
const trashBusy = ref(false);
const trashError = ref("");

let reqGen = 0;
let searchTimer: ReturnType<typeof setTimeout> | undefined;

const base = () => `/api/v1/companies/${encodeURIComponent(props.company.id)}/directories/${encodeURIComponent(props.dirKey)}/files`;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

async function load(): Promise<void> {
  clearTimeout(searchTimer);
  const mine = ++reqGen;
  loading.value = true;
  error.value = "";
  const params = new URLSearchParams();
  if (subpath.value) params.set("subpath", subpath.value);
  if (q.value.trim()) params.set("q", q.value.trim());
  if (extFilter.value) params.set("ext", extFilter.value);
  params.set("sort_by", sortBy.value);
  params.set("sort_dir", sortDir.value);
  try {
    const res = await request<DirectoryFilesPayload>(`${base()}?${params.toString()}`);
    if (mine !== reqGen) return;
    data.value = res;
  } catch (cause) {
    if (mine === reqGen) error.value = errorText(cause);
  } finally {
    if (mine === reqGen) loading.value = false;
  }
}

function scheduleLoad(): void {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => void load(), 200);
}

function openSubpath(next: string): void {
  subpath.value = next;
  stagedFiles.value = [];
  importPreview.value = null;
  uploadResults.value = [];
  void load();
}

async function createSubfolder(): Promise<void> {
  const name = mkdirName.value.trim();
  if (!name || mkdirBusy.value) return;
  mkdirBusy.value = true;
  error.value = "";
  try {
    await request(`${base()}/mkdir`, { method: "POST", body: { subpath: subpath.value, name } });
    mkdirName.value = "";
    mkdirOpen.value = false;
    toast(`已创建子文件夹「${name}」。`);
    await load();
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    mkdirBusy.value = false;
  }
}

async function stageFilesForImport(list: FileList | File[]): Promise<void> {
  const files = Array.from(list).filter((file) => file && file.name);
  if (!files.length) return;
  stagedFiles.value = files;
  uploadResults.value = [];
  await refreshImportPreview();
}

async function refreshImportPreview(): Promise<void> {
  if (!stagedFiles.value.length) {
    importPreview.value = null;
    return;
  }
  error.value = "";
  try {
    importPreview.value = await request<FileImportPreviewPayload>(`${base()}/import-preview`, {
      method: "POST",
      body: {
        subpath: subpath.value,
        conflict_policy: uploadConflictPolicy.value,
        filenames: stagedFiles.value.map((file) => file.name),
      },
    });
  } catch (cause) {
    error.value = errorText(cause);
    importPreview.value = null;
  }
}

watch(uploadConflictPolicy, () => {
  if (stagedFiles.value.length) void refreshImportPreview();
});

function onDrop(event: DragEvent): void {
  dragOver.value = false;
  if (event.dataTransfer?.files?.length) {
    void stageFilesForImport(event.dataTransfer.files);
  }
}

function onFilePicked(event: Event): void {
  const input = event.target as HTMLInputElement;
  if (input.files?.length) {
    void stageFilesForImport(input.files);
    input.value = "";
  }
}

async function confirmUpload(): Promise<void> {
  if (!stagedFiles.value.length || uploading.value) return;
  uploading.value = true;
  error.value = "";
  uploadResults.value = [];
  let importedCount = 0;
  let skippedCount = 0;
  try {
    for (let idx = 0; idx < stagedFiles.value.length; idx += 1) {
      const file = stagedFiles.value[idx]!;
      uploadProgress.value = `正在导入 ${idx + 1}/${stagedFiles.value.length}：${file.name}`;
      const params = new URLSearchParams({
        filename: file.name,
        subpath: subpath.value,
        conflict_policy: uploadConflictPolicy.value,
      });
      const response = await fetch(`${base()}/upload?${params.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      const body = await response.json().catch(() => ({})) as FileUploadResult & { detail?: string; error?: { message?: string } };
      if (!response.ok) {
        throw new Error(body.error?.message || body.detail || `导入「${file.name}」失败（HTTP ${response.status}）`);
      }
      uploadResults.value.push(body);
      if (body.status === "skipped") skippedCount += 1;
      else importedCount += 1;
    }
    stagedFiles.value = [];
    importPreview.value = null;
    toast(`导入完成：写入 ${importedCount} 个${skippedCount ? `，跳过 ${skippedCount} 个` : ""}。`, "info", 4500);
    await load();
    emit("mutated");
    if (props.isInvoiceDir && importedCount > 0) {
      if (data.value?.monitored) {
        await request("/api/v1/bridge/rebuild", { method: "POST", body: {} }).catch(() => undefined);
      } else {
        void companies.refreshData(props.company.id, { keys: [props.dirKey], force: true, silent: true });
      }
      window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    }
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    uploading.value = false;
    uploadProgress.value = "";
  }
}

async function openFile(entry: DirectoryFileEntry, reveal: boolean): Promise<void> {
  if (!data.value?.can_mutate_existing || entry.is_symlink) return;
  try {
    await request(`${base()}/open`, { method: "POST", body: { relative_path: entry.relative_path, reveal } });
  } catch (cause) {
    toast(errorText(cause), "error", 4000);
  }
}

function startRename(entry: DirectoryFileEntry): void {
  renameTarget.value = entry;
  renameValue.value = entry.name;
  renameError.value = "";
}

async function submitRename(): Promise<void> {
  const target = renameTarget.value;
  if (!target || renameBusy.value) return;
  const nextName = renameValue.value.trim();
  if (!nextName) {
    renameError.value = "新文件名不能为空。";
    return;
  }
  renameBusy.value = true;
  renameError.value = "";
  try {
    const res = await request<FileRenameResult>(`${base()}/rename`, {
      method: "POST",
      body: { relative_path: target.relative_path, new_name: nextName },
    });
    renameTarget.value = null;
    toast(res.renamed ? `已重命名为「${res.new_name}」。` : "文件名未变化。");
    await load();
    if (res.renamed && props.isInvoiceDir && res.monitored) {
      await request("/api/v1/bridge/rebuild", { method: "POST", body: {} }).catch(() => undefined);
      window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    }
    emit("mutated");
  } catch (cause) {
    renameError.value = errorText(cause);
  } finally {
    renameBusy.value = false;
  }
}

async function onMoved(result: FileMovePlanPayload): Promise<void> {
  movePaths.value = null;
  await load();
  if ((result.moved ?? 0) > 0 && props.isInvoiceDir && data.value?.monitored) {
    await request("/api/v1/bridge/rebuild", { method: "POST", body: {} }).catch(() => undefined);
  }
  window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
  emit("mutated");
}

async function startTrash(entry: DirectoryFileEntry): Promise<void> {
  trashError.value = "";
  trashConfirmed.value = false;
  try {
    trashPreview.value = await request<FileTrashPreviewPayload>(`${base()}/trash/preview`, {
      method: "POST",
      body: { relative_paths: [entry.relative_path] },
    });
  } catch (cause) {
    toast(errorText(cause), "error", 4000);
  }
}

async function confirmTrash(): Promise<void> {
  const preview = trashPreview.value;
  if (!preview || !trashConfirmed.value || trashBusy.value) return;
  trashBusy.value = true;
  trashError.value = "";
  try {
    const res = await request<FileTrashConfirmPayload>(`${base()}/trash`, {
      method: "POST",
      body: {
        confirm: true,
        plan_hash: preview.plan_hash,
        relative_paths: preview.items.map((item) => item.relative_path),
      },
    });
    trashPreview.value = null;
    toast(`已移入系统回收站 ${res.trashed} 个文件。`, res.failed ? "error" : "info", 4000);
    await load();
    if (res.trashed > 0 && props.isInvoiceDir && res.monitored) {
      await request("/api/v1/bridge/rebuild", { method: "POST", body: {} }).catch(() => undefined);
    }
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    emit("mutated");
  } catch (cause) {
    trashError.value = errorText(cause);
  } finally {
    trashBusy.value = false;
  }
}

const canMutate = computed(() => Boolean(data.value?.can_mutate_existing));

watch([extFilter, sortBy, sortDir], () => void load());
watch(
  () => `${companySourceKey(props.company, [props.dirKey])}/${props.company.monitored}/${props.company.monitored_subdir_key ?? ""}`,
  () => {
    subpath.value = "";
    stagedFiles.value = [];
    importPreview.value = null;
    uploadResults.value = [];
    void load();
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  ++reqGen;
  clearTimeout(searchTimer);
});
</script>

<template>
  <section class="panel ws-files" aria-label="目录文件管理">
    <div class="overview-section__head">
      <div>
        <h3>目录文件与导入 <span v-if="data" class="muted">· {{ data.total_folders }} 个子文件夹 · {{ data.total_files }} 个文件</span></h3>
        <p v-if="data && !canMutate" class="muted">
          当前为未监控发票目录：支持浏览子文件夹和导入新文件（绝不覆盖同名文件）；如需打开、重命名、移动或删除现有源发票，请先将其设为监控目录。
        </p>
        <p v-else class="muted">支持拖放或选择文件导入（不覆盖同名文件）、创建子文件夹、重命名、跨目录移动及移入系统回收站。</p>
      </div>
      <div class="ws-files__head-actions">
        <button type="button" class="ghost" @click="mkdirOpen = !mkdirOpen">+ 新建子文件夹</button>
        <button type="button" class="primary" @click="fileInputRef?.click()">选择文件导入…</button>
        <input ref="fileInputRef" type="file" multiple hidden aria-label="选择要导入的文件" @change="onFilePicked">
      </div>
    </div>

    <nav v-if="data?.breadcrumbs?.length" class="ws-files__crumbs" aria-label="当前路径">
      <template v-for="(crumb, idx) in data.breadcrumbs" :key="crumb.subpath">
        <span v-if="idx > 0" class="muted">/</span>
        <button type="button" class="link" :aria-current="idx === data.breadcrumbs.length - 1 ? 'location' : undefined" @click="openSubpath(crumb.subpath)">
          {{ crumb.name }}
        </button>
      </template>
    </nav>

    <form v-if="mkdirOpen" class="ws-files__mkdir" @submit.prevent="createSubfolder">
      <input v-model="mkdirName" type="text" maxlength="120" placeholder="输入新建子文件夹名称（如 2026-11）" aria-label="新建子文件夹名称">
      <button type="submit" class="primary" :disabled="mkdirBusy || !mkdirName.trim()">创建</button>
      <button type="button" :disabled="mkdirBusy" @click="mkdirOpen = false; mkdirName = ''">取消</button>
    </form>

    <div
      class="ws-files__dropzone"
      :class="{ 'ws-files__dropzone--over': dragOver }"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
    >
      <span>将本机文件拖放到此处，或点击「选择文件导入…」添加到当前目录{{ subpath ? `（${subpath}）` : "" }}</span>
    </div>

    <div v-if="importPreview" class="ws-files__import-box">
      <div class="ws-files__import-head">
        <strong>待导入 {{ stagedFiles.length }} 个文件</strong>
        <label>
          <span>同名策略</span>
          <select v-model="uploadConflictPolicy" aria-label="导入同名文件策略" :disabled="uploading">
            <option value="rename">自动追加序号保留两份（推荐）</option>
            <option value="skip">跳过已有同名文件</option>
          </select>
        </label>
        <button type="button" class="primary" :disabled="uploading || (importPreview.summary.write + importPreview.summary.rename === 0)" :aria-busy="uploading" @click="confirmUpload">
          {{ uploading ? (uploadProgress || "导入中…") : `确认导入（写入 ${importPreview.summary.write + importPreview.summary.rename} 个）` }}
        </button>
        <button type="button" :disabled="uploading" @click="stagedFiles = []; importPreview = null">取消</button>
      </div>
      <ul class="ws-files__import-list">
        <li v-for="item in importPreview.items" :key="item.original_name">
          <span class="mono">{{ item.original_name }}</span>
          <span v-if="item.action === 'write'" class="muted">→ 直接保存</span>
          <span v-else-if="item.action === 'rename'" class="muted">→ {{ item.reason }}</span>
          <span v-else-if="item.action === 'skip'" class="muted">→ 跳过（已有同名）</span>
          <strong v-else class="check--failed">→ 阻断：{{ item.reason }}</strong>
        </li>
      </ul>
    </div>

    <div v-if="uploadResults.length" class="banner banner--note" role="status">
      最近导入结果：{{ uploadResults.map((r) => `${r.saved_name}（${r.status === "skipped" ? "已跳过" : r.status === "renamed" ? "已改名保存" : "已导入"}）`).join("；") }}
      <button type="button" class="link" @click="uploadResults = []">关闭</button>
    </div>

    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

    <div class="ws-files__filters">
      <input v-model="q" type="search" placeholder="按文件名搜索当前目录…" aria-label="按文件名搜索当前目录" @input="scheduleLoad" @keydown.enter.prevent="load">
      <select v-model="extFilter" aria-label="按扩展名筛选">
        <option value="">全部类型</option>
        <option v-for="ext in data?.extensions ?? []" :key="ext" :value="ext">{{ ext }}</option>
      </select>
      <select v-model="sortBy" aria-label="文件排序字段">
        <option value="name">按名称</option>
        <option value="mtime">按修改时间</option>
        <option value="size">按大小</option>
      </select>
      <select v-model="sortDir" aria-label="文件排序方向">
        <option value="asc">升序</option>
        <option value="desc">降序</option>
      </select>
      <button type="button" class="ghost" :disabled="loading" @click="load">刷新</button>
    </div>

    <p v-if="loading && !data" class="muted" role="status" aria-busy="true">正在读取目录文件…</p>
    <p v-if="data?.truncated" class="banner banner--note" role="status">当前目录条目数超过 2000 项，仅展示前 2000 项；请进入子文件夹或输入关键字缩小范围。</p>

    <div v-if="data" class="overview-table-wrap">
      <table class="grid ws-files__table" aria-label="目录文件清单">
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th class="num">大小</th>
            <th>修改时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="subpath">
            <td colspan="5">
              <button type="button" class="link" @click="openSubpath(subpath.includes('/') ? subpath.slice(0, subpath.lastIndexOf('/')) : '')">
                ← 返回上一级目录
              </button>
            </td>
          </tr>
          <tr v-for="folder in data.folders" :key="`dir:${folder.relative_path}`">
            <td>
              <button type="button" class="link ws-files__folder-btn" @click="openSubpath(folder.relative_path)">
                📁 {{ folder.name }}
              </button>
            </td>
            <td class="muted">文件夹</td>
            <td class="num muted">—</td>
            <td class="mono muted nowrap">{{ folder.mtime || "—" }}</td>
            <td><button type="button" class="ghost" @click="openSubpath(folder.relative_path)">进入</button></td>
          </tr>
          <tr v-for="file in data.files" :key="`file:${file.relative_path}`">
            <td class="path mono" :title="file.relative_path">
              {{ file.name }}
              <span v-if="file.is_symlink" class="tag">符号链接（已禁用）</span>
            </td>
            <td class="muted">{{ file.ext || "文件" }}</td>
            <td class="num mono">{{ file.is_symlink ? "—" : formatSize(file.size_bytes) }}</td>
            <td class="mono muted nowrap">{{ file.mtime || "—" }}</td>
            <td>
              <div class="row-actions">
                <template v-if="canMutate && !file.is_symlink">
                  <button type="button" class="ghost" @click="openFile(file, false)">打开</button>
                  <button type="button" class="ghost" @click="openFile(file, true)">位置</button>
                  <button type="button" class="ghost" @click="startRename(file)">重命名</button>
                  <button type="button" class="ghost" @click="movePaths = [file.relative_path]">移动</button>
                  <button type="button" class="ghost danger-text" @click="startTrash(file)">回收站</button>
                </template>
                <span v-else class="muted">{{ file.is_symlink ? "链接禁用" : "只读" }}</span>
              </div>
            </td>
          </tr>
          <tr v-if="!data.folders.length && !data.files.length">
            <td colspan="5" class="muted">当前目录下暂无匹配的文件或子文件夹。</td>
          </tr>
        </tbody>
      </table>
    </div>

    <WsModal v-if="renameTarget" title="重命名文件" :subtitle="`当前文件：${renameTarget.relative_path}`" @close="renameTarget = null">
      <form class="ws-files__modal-form" @submit.prevent="submitRename">
        <p v-if="renameError" class="banner banner--error" role="alert">{{ renameError }}</p>
        <label>
          <span>新文件名（含扩展名）</span>
          <input v-model="renameValue" type="text" maxlength="180" aria-label="输入新文件名">
        </label>
        <p class="muted">重命名绝不覆盖同目录下的已有文件；如为监控目录中的发票，会同步迁移已保存的手改字段。</p>
        <div class="actions">
          <button type="submit" class="primary" :disabled="renameBusy" :aria-busy="renameBusy">{{ renameBusy ? "重命名中…" : "确认重命名" }}</button>
          <button type="button" :disabled="renameBusy" @click="renameTarget = null">取消</button>
        </div>
      </form>
    </WsModal>

    <FileMoveModal
      v-if="movePaths"
      :company="company"
      :dir-key="dirKey"
      :relative-paths="movePaths"
      @close="movePaths = null"
      @moved="onMoved"
    />

    <WsModal v-if="trashPreview" title="移入系统回收站" :subtitle="`目录：${trashPreview.dir_label}`" @close="trashPreview = null">
      <div class="ws-files__modal-form">
        <p v-if="trashError" class="banner banner--error" role="alert">{{ trashError }}</p>
        <p>
          将以下 <strong>{{ trashPreview.file_count }}</strong> 个文件（共 {{ formatSize(trashPreview.total_bytes) }}）移入系统回收站 / 废纸篓（支持从系统回收站恢复，绝不执行永久删除）：
        </p>
        <ul>
          <li v-for="item in trashPreview.items" :key="item.relative_path" class="mono">{{ item.relative_path }}</li>
        </ul>
        <label class="ws-files__confirm-check">
          <input v-model="trashConfirmed" type="checkbox">
          <span>我已核对文件名，确认移入系统回收站</span>
        </label>
        <div class="actions">
          <button type="button" class="danger" :disabled="!trashConfirmed || trashBusy" :aria-busy="trashBusy" @click="confirmTrash">
            {{ trashBusy ? "移入中…" : "确认移入系统回收站" }}
          </button>
          <button type="button" :disabled="trashBusy" @click="trashPreview = null">取消</button>
        </div>
      </div>
    </WsModal>
  </section>
</template>

<style scoped>
.ws-files { display: grid; gap: 12px; }
.ws-files__head-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.ws-files__crumbs { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 13px; }
.ws-files__mkdir { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ws-files__mkdir input { flex: 1 1 220px; }
.ws-files__dropzone {
  padding: 14px 16px;
  border: 1.5px dashed var(--line-strong, var(--line));
  border-radius: 6px;
  background: var(--surface-2, var(--bg));
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}
.ws-files__dropzone--over { border-color: var(--accent); color: var(--text); }
.ws-files__import-box { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); }
.ws-files__import-head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.ws-files__import-head label { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.ws-files__import-list { margin: 0; padding-left: 18px; display: grid; gap: 4px; font-size: 12px; }
.ws-files__filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ws-files__filters input { flex: 1 1 200px; }
.ws-files__folder-btn { font-weight: 500; }
.ws-files__table td.path { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ws-files__table .row-actions { display: flex; flex-wrap: wrap; gap: 4px; }
.ws-files__modal-form { display: grid; gap: 12px; }
.ws-files__modal-form label { display: grid; gap: 4px; font-size: 13px; }
.ws-files__confirm-check { display: flex !important; align-items: center; gap: 8px; }
.danger-text { color: var(--red); }
</style>
