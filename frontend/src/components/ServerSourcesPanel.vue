<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { request } from "../api/client";
import { errorText, money } from "../format";
import { useCompaniesStore } from "../stores/companies";
import {
  CONNECTION_LABELS,
  PHASE_LABELS,
  formatBytes,
  isSourceRunning,
  type ServerEntry,
  type ServerListing,
  type ServerPreviewJob,
  type ServerSource,
  type ServerSummaryPayload,
  useSourcesStore,
} from "../stores/sources";
import WorkspaceIcon from "./WorkspaceIcon.vue";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{
  close: [];
  openConnect: [];
  openWorkspace: [payload: { sourceId: string; parentId: string; sourceName: string; dirName: string }];
}>();

const companies = useCompaniesStore();
const store = useSourcesStore();

const expanded = ref(false);
const busy = ref(false);
const error = ref("");
const parent = ref("");
const keyword = ref("");
const page = ref(1);
const listing = ref<ServerListing>();
const summary = ref<ServerSummaryPayload>();
const preview = ref<ServerPreviewJob>();
const text = ref("");
const previewPage = ref(1);
const tabs = ref<ServerEntry[]>([]);
const activeTab = ref<"directory" | string>("directory");
const pendingPreview = ref("");
const company = ref("");
const role = ref("cost_invoice_dir");
const budget = ref(1024);

const selected = computed({
  get: () => store.selectedId,
  set: (value: string) => {
    store.selectedId = value;
  },
});
const source = computed(() => store.byId(selected.value));
const running = computed(() => isSourceRunning(source.value));
const progress = computed(() => source.value?.progress);
const currentDirName = computed(() => listing.value?.breadcrumbs.at(-1)?.name ?? source.value?.name ?? "服务器目录");
const directSubdirs = computed(() => (listing.value?.items ?? []).filter((item) => item.kind === "directory"));
const progressPercent = computed(() => {
  if (!running.value) return 0;
  const p = progress.value;
  if (p?.total && p.total > 0) return Math.min(100, Math.round(((p.completed ?? 0) / p.total) * 100));
  if (p?.total_bytes && p.total_bytes > 0) return Math.min(100, Math.round(((p.bytes ?? 0) / p.total_bytes) * 100));
  return 0;
});

let timer: ReturnType<typeof setTimeout> | undefined;
let turn = 0;
let previewTurn = 0;
let wasRunning = false;

async function action<T>(fn: () => Promise<T>): Promise<T | undefined> {
  error.value = "";
  busy.value = true;
  try {
    return await fn();
  } catch (cause) {
    error.value = errorText(cause);
    return undefined;
  } finally {
    busy.value = false;
  }
}

function syncSettingsForm(current: ServerSource | null): void {
  company.value = current?.binding?.company_id ?? "";
  role.value = current?.binding?.role ?? "cost_invoice_dir";
  budget.value = Math.round((current?.cache_budget ?? 1024 ** 3) / 1024 ** 2);
}

async function load(): Promise<void> {
  await action(async () => {
    const list = await store.load();
    if (store.loadError) error.value = store.loadError;
    const id = list.find((item) => item.id === selected.value)?.id ?? list[0]?.id ?? "";
    // Rehydrate saved binding/budget before exposing Save after reopening.
    if (id) {
      await select(id);
    } else {
      selected.value = "";
      listing.value = undefined;
      summary.value = undefined;
    }
  });
}

async function refresh(): Promise<void> {
  clearTimeout(timer);
  if (!selected.value || !props.open) return;
  const id = selected.value;
  const epoch = ++turn;
  try {
    const [data, totals] = await Promise.all([
      request<ServerListing>(
        `/api/v1/sources/${id}/entries?parent_id=${encodeURIComponent(parent.value)}&page=${page.value}&keyword=${encodeURIComponent(keyword.value)}`,
      ),
      request<ServerSummaryPayload>(
        `/api/v1/sources/${id}/summary?parent_id=${encodeURIComponent(parent.value)}&page=1&page_size=20`,
      ),
    ]);
    if (id !== selected.value || epoch !== turn) return;
    listing.value = data;
    store.upsert(data.source);
    summary.value = totals;
    const nowRunning = isSourceRunning(data.source);
    if (wasRunning && !nowRunning) store.notifyUpdated();
    wasRunning = nowRunning;
    if (!nowRunning && pendingPreview.value) {
      const entryId = pendingPreview.value;
      pendingPreview.value = "";
      if (!data.source.error && data.source.connection === "online") await showPreview(entryId, false);
    }
  } catch (cause) {
    if (epoch === turn) error.value = errorText(cause);
  }
  if (props.open && running.value) timer = setTimeout(() => void refresh(), 700);
}

async function select(id: string): Promise<void> {
  const epoch = ++turn;
  await closePreview();
  if (epoch !== turn) return;
  selected.value = id;
  parent.value = "";
  page.value = 1;
  keyword.value = "";
  activeTab.value = "directory";
  pendingPreview.value = "";
  tabs.value = [];
  wasRunning = isSourceRunning(source.value);
  syncSettingsForm(source.value);
  await refresh();
}

async function start(kind: string, extra: Record<string, unknown> = {}): Promise<void> {
  await action(async () => {
    const result = await request<{ source: ServerSource }>(`/api/v1/sources/${selected.value}/tasks`, {
      method: "POST",
      body: { kind, ...extra },
    });
    store.upsert(result.source);
    wasRunning = isSourceRunning(result.source);
    await refresh();
  });
}

async function confirmFingerprint(fingerprint: string): Promise<void> {
  await action(async () => {
    const result = await request<{ source: ServerSource }>(`/api/v1/sources/${selected.value}/fingerprint`, {
      method: "POST",
      body: { revision: source.value?.revision, fingerprint },
    });
    store.upsert(result.source);
  });
}

async function stop(disconnect = false): Promise<void> {
  await action(async () => {
    const result = await request<{ source: ServerSource }>(
      `/api/v1/sources/${selected.value}/${disconnect ? "disconnect" : "cancel"}`,
      { method: "POST", body: {} },
    );
    store.upsert(result.source);
    pendingPreview.value = "";
    wasRunning = false;
    store.notifyUpdated();
    await refresh();
  });
}

async function directory(id: string): Promise<void> {
  await closePreview();
  parent.value = id;
  page.value = 1;
  keyword.value = "";
  activeTab.value = "directory";
  await refresh();
}

async function openEntry(entry: ServerEntry): Promise<void> {
  if (entry.kind === "directory") {
    await directory(entry.id);
    return;
  }
  if (!tabs.value.some((tab) => tab.id === entry.id)) tabs.value.push(entry);
  activeTab.value = entry.id;
  if (source.value?.connection === "online") {
    if (entry.cached) {
      await showPreview(entry.id, false);
    } else {
      pendingPreview.value = entry.id;
      await start("download", { entry_id: entry.id });
    }
  } else {
    await showPreview(entry.id, true);
  }
}

async function activateDirectoryTab(): Promise<void> {
  activeTab.value = "directory";
  await closePreview();
}

async function closeFileTab(entryId: string): Promise<void> {
  tabs.value = tabs.value.filter((item) => item.id !== entryId);
  if (activeTab.value === entryId) {
    activeTab.value = "directory";
    await closePreview();
  }
}

async function showPreview(id: string, stale: boolean): Promise<void> {
  await action(async () => {
    const sid = selected.value;
    await closePreview();
    const epoch = previewTurn;
    const result = await request<ServerPreviewJob>(`/api/v1/sources/${sid}/previews`, {
      method: "POST",
      body: { entry_id: id, allow_stale: stale },
    });
    // Closing or switching while rendering invalidates the request and its server lease.
    if (sid !== selected.value || epoch !== previewTurn || !props.open) {
      await request(`/api/v1/sources/${sid}/previews/${result.job_id}`, { method: "DELETE" }).catch(() => undefined);
      return;
    }
    preview.value = result;
    previewPage.value = 1;
    text.value = "";
    if (result.preview_type === "text") {
      const content = await request<{ text: string }>(`/api/v1/sources/${sid}/previews/${result.job_id}/text`);
      if (sid === selected.value && preview.value?.job_id === result.job_id) text.value = content.text;
    }
  });
}

async function saveSettings(): Promise<void> {
  await action(async () => {
    const result = await request<{ source: ServerSource }>(`/api/v1/sources/${selected.value}`, {
      method: "PATCH",
      body: {
        revision: source.value?.revision,
        cache_budget: Math.round(budget.value * 1024 ** 2),
        binding: company.value ? { company_id: company.value, role: role.value } : null,
      },
    });
    store.upsert(result.source);
    store.notifyUpdated();
    await closePreview();
    await refresh();
  });
}

async function onPreviewImageError(): Promise<void> {
  const current = preview.value;
  const sid = selected.value;
  const page = previewPage.value;
  const epoch = previewTurn;
  if (!current || !sid) return;
  try {
    const response = await fetch(`/api/v1/sources/${sid}/previews/${current.job_id}/pages/${page}`, {
      credentials: "same-origin",
    });
    if (epoch !== previewTurn || sid !== selected.value || preview.value?.job_id !== current.job_id || page !== previewPage.value) {
      return;
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      const detail = payload && typeof payload.detail === "string" ? payload.detail.trim() : "";
      if (detail) {
        error.value = detail;
        return;
      }
    }
  } catch {
    if (epoch !== previewTurn || sid !== selected.value) return;
  }
  error.value = "预览授权过期或文件变化，请重新打开。";
}

async function closePreview(): Promise<void> {
  ++previewTurn;
  const old = preview.value;
  const sid = selected.value;
  preview.value = undefined;
  text.value = "";
  if (old) {
    await request(`/api/v1/sources/${sid}/previews/${old.job_id}`, { method: "DELETE" }).catch(() => undefined);
  }
}

async function forget(): Promise<void> {
  if (!source.value || !window.confirm("移除此来源收藏和本机缓存？服务器文件不会改动。")) return;
  await action(async () => {
    const removedId = selected.value;
    await closePreview();
    await request(`/api/v1/sources/${removedId}?revision=${source.value?.revision}`, { method: "DELETE" });
    store.remove(removedId);
    listing.value = undefined;
    summary.value = undefined;
    await load();
  });
}

async function clearCache(): Promise<void> {
  await action(async () => {
    await request(`/api/v1/sources/${selected.value}/cache`, { method: "DELETE" });
    store.notifyUpdated();
    await refresh();
  });
}

function openInWorkspace(): void {
  if (!source.value) return;
  emit("openWorkspace", {
    sourceId: source.value.id,
    parentId: parent.value,
    sourceName: source.value.name,
    dirName: currentDirName.value,
  });
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      void load();
    } else {
      ++turn;
      clearTimeout(timer);
      void closePreview();
    }
  },
  { immediate: true },
);

watch(
  () => store.selectedId,
  (nextId, prevId) => {
    if (props.open && nextId && nextId !== prevId) {
      void select(nextId);
    }
  },
);

watch(
  () => store.revisionTick,
  () => {
    if (props.open && selected.value && !running.value) void refresh();
  },
);

onBeforeUnmount(() => {
  ++turn;
  clearTimeout(timer);
  void closePreview();
});
</script>

<template>
  <aside
    v-if="open"
    class="server-panel"
    :class="{ 'server-panel--wide': expanded }"
    aria-label="服务器文件"
    @keydown.esc.stop="activeTab !== 'directory' ? activateDirectoryTab() : emit('close')"
  >
    <header class="server-panel__head">
      <div class="server-panel__title">
        <WorkspaceIcon name="server" />
        <div>
          <strong>服务器文件 <small>试验版 · 只读</small></strong>
          <p v-if="source" class="muted server-panel__sub">{{ source.name }}</p>
        </div>
      </div>
      <div class="server-panel__controls">
        <span
          v-if="source"
          class="tag"
          :class="source.connection === 'online' ? 'pill-ok' : source.connection === 'connecting' ? 'pill-warn' : ''"
        >{{ CONNECTION_LABELS[source.connection] ?? source.connection }}</span>
        <button type="button" class="ghost" @click="emit('openConnect')">连接管理</button>
        <button
          type="button"
          class="ghost"
          :aria-label="expanded ? '还原文件面板' : '放大文件面板'"
          @click="expanded = !expanded"
        >{{ expanded ? "还原" : "放大" }}</button>
        <button type="button" class="ghost" aria-label="收起服务器文件" @click="emit('close')">收起</button>
      </div>
    </header>

    <div class="server-picker-bar">
      <label class="server-picker-bar__select">
        <span class="sr-only">收藏来源</span>
        <select :value="selected" aria-label="收藏来源" @change="select(($event.target as HTMLSelectElement).value)">
          <option value="">选择收藏来源…</option>
          <option v-for="item in store.sources" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
      </label>
      <button type="button" @click="emit('openConnect')">添加</button>
    </div>

    <div v-if="source && listing" class="server-path-bar">
      <nav class="breadcrumbs" aria-label="服务器目录路径">
        <button v-for="(crumb, idx) in listing.breadcrumbs" :key="crumb.id" type="button" @click="directory(crumb.id)">
          {{ crumb.name }}<span v-if="idx < listing.breadcrumbs.length - 1"> ›</span>
        </button>
      </nav>
      <div class="server-path-bar__meta muted">
        <span>当前目录（含子目录）：{{ listing.scope.files }} 个文件 · {{ formatBytes(listing.scope.bytes) }}</span>
        <label class="subdir-picker">
          <span class="sr-only">子目录</span>
          <select aria-label="切换服务器目录" :value="''" @change="directory(($event.target as HTMLSelectElement).value)">
            <option value="" disabled>跳转子目录 ({{ directSubdirs.length }})</option>
            <option v-for="dir in directSubdirs" :key="dir.id" :value="dir.id">{{ dir.name }}</option>
          </select>
        </label>
      </div>
    </div>

    <nav v-if="source" class="server-tabs" role="tablist" aria-label="服务器文件标签">
      <div class="server-tab" :class="{ 'is-active': activeTab === 'directory' }">
        <button
          type="button"
          role="tab"
          :aria-selected="activeTab === 'directory'"
          @click="activateDirectoryTab"
        >
          <WorkspaceIcon name="folder" />
          <span>{{ currentDirName }}</span>
        </button>
        <span
          v-if="running && activeTab === 'directory'"
          class="server-tab__line"
          :class="{ 'is-indeterminate': !progressPercent }"
          :style="progressPercent ? { width: `${progressPercent}%` } : undefined"
        />
      </div>
      <div
        v-for="tab in tabs"
        :key="tab.id"
        class="server-tab"
        :class="{ 'is-active': activeTab === tab.id }"
      >
        <button
          type="button"
          role="tab"
          :aria-selected="activeTab === tab.id"
          @click="openEntry(tab)"
        >
          <span>{{ source.connection === "online" ? "" : "查看离线副本 · " }}{{ tab.name }}</span>
        </button>
        <button
          type="button"
          class="server-tab__close"
          :aria-label="`关闭 ${tab.name}`"
          @click.stop="closeFileTab(tab.id)"
        >×</button>
        <span
          v-if="running && activeTab === tab.id"
          class="server-tab__line"
          :class="{ 'is-indeterminate': !progressPercent }"
          :style="progressPercent ? { width: `${progressPercent}%` } : undefined"
        />
      </div>
    </nav>

    <div class="server-body">
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <div v-if="!source" class="empty-state">
        <strong>还没有已连接的服务器目录</strong>
        <p class="muted">先添加系统已挂载的 SMB 共享文件夹或 SSH/SFTP 来源，再浏览并汇总其中的发票。</p>
        <button type="button" class="primary" @click="emit('openConnect')">连接服务器</button>
      </div>

      <template v-else>
        <p v-if="source.error" class="banner banner--error" role="alert">{{ source.error }}</p>

        <div v-if="running" class="source-progress" role="status">
          <div class="source-progress__row">
            <span>
              {{ PHASE_LABELS[progress?.phase ?? source.sync] ?? source.sync }}
              <template v-if="progress?.total !== undefined"> · {{ progress.completed ?? 0 }} / {{ progress.total }}</template>
              <template v-else-if="progress?.enumerated !== undefined"> · 已枚举 {{ progress.enumerated }} 项</template>
              <template v-if="progress?.bytes !== undefined"> · {{ formatBytes(progress.bytes) }} / {{ formatBytes(progress.total_bytes ?? 0) }}</template>
            </span>
            <button type="button" class="ghost" @click="stop()">取消</button>
          </div>
          <progress :value="progress?.total ? progress.completed : undefined" :max="progress?.total ?? 1" />
        </div>

        <div v-if="source.fingerprints.length" class="fingerprints">
          <p>请通过管理员提供的独立渠道核对指纹；确认后方可连接。</p>
          <div v-for="fp in source.fingerprints" :key="fp" class="fingerprint-row">
            <code>{{ fp }}</code>
            <button
              type="button"
              :disabled="source.fingerprint === fp || !!running || busy"
              @click="confirmFingerprint(fp)"
            >{{ source.fingerprint === fp ? "已确认" : "已核对，信任此指纹" }}</button>
          </div>
        </div>

        <!-- Directory browsing tab -->
        <template v-if="activeTab === 'directory'">
          <div class="actions server-actions">
            <button
              v-if="source.protocol === 'sftp'"
              type="button"
              :disabled="!!running || busy"
              @click="start('probe')"
            >读取主机指纹</button>
            <button
              v-if="!source.generation || source.connection !== 'online'"
              type="button"
              class="primary"
              :disabled="!!running || busy"
              @click="start('scan')"
            >连接 / 刷新目录</button>
            <template v-else>
              <button
                v-if="summary?.available"
                type="button"
                class="primary"
                @click="openInWorkspace"
              >在工作区打开汇总 ↗</button>
              <button
                v-else
                type="button"
                class="primary"
                :disabled="!!running || busy"
                @click="start('summary', { parent_id: parent })"
              >汇总此目录</button>
              <button
                v-if="summary?.available"
                type="button"
                :disabled="!!running || busy"
                @click="start('summary', { parent_id: parent })"
              >增量刷新</button>
              <button
                v-else
                type="button"
                @click="openInWorkspace"
              >工作区视图 ↗</button>
              <button
                type="button"
                class="ghost"
                :disabled="!!running || busy"
                @click="start('scan')"
              >刷新目录</button>
            </template>
            <button v-if="source.connection === 'online'" type="button" class="ghost" @click="stop(true)">断开</button>
          </div>

          <section v-if="summary?.available" class="summary-card" aria-label="当前目录汇总概览">
            <div class="summary-card__head">
              <div>
                <strong>{{ currentDirName }} · {{ summary.invoice_stats?.all.total ?? summary.count ?? 0 }} 条发票记录</strong>
                <p class="muted">
                  价税合计 {{ money(summary.invoice_stats?.all.total_amount ?? summary.ledger?.totals.input.total ?? "") }}
                  <template v-if="summary.invoice_stats?.all.needs_review"> · 待核对 {{ summary.invoice_stats.all.needs_review }} 张</template>
                </p>
              </div>
              <button type="button" class="primary" @click="openInWorkspace">打开完整发票表 ↗</button>
            </div>
            <p class="muted summary-card__meta">
              {{ summary.stale ? "上次完整结果，当前未核验" : "完整结果" }} · {{ summary.last_complete_at }}
              · 解析 {{ summary.stats?.parsed ?? 0 }} / 复用 {{ summary.stats?.reused ?? 0 }}
            </p>
          </section>

          <form class="filter" @submit.prevent="page = 1; refresh()">
            <input v-model="keyword" aria-label="筛选服务器文件" placeholder="筛选当前目录文件或子文件夹">
            <button type="submit">筛选</button>
          </form>

          <ul class="server-files">
            <li v-for="entry in listing?.items" :key="entry.id">
              <button
                type="button"
                :disabled="!!running && entry.kind === 'file'"
                @click="openEntry(entry)"
              >
                <span class="server-files__name">
                  <WorkspaceIcon :name="entry.kind === 'directory' ? 'folder' : 'docs'" />
                  <span>{{ entry.name }}</span>
                </span>
                <small>
                  <template v-if="entry.kind === 'directory'">文件夹</template>
                  <template v-else>
                    {{ source.connection === "online" ? (entry.cached ? "已缓存 · " : "") : "查看离线副本 · " }}{{ formatBytes(entry.size) }}
                  </template>
                </small>
              </button>
            </li>
          </ul>

          <p v-if="!source.generation" class="muted">尚无完整缓存，请点击「连接 / 刷新目录」读取此共享目录。</p>
          <p
            v-else-if="listing && !source.error && (keyword ? !listing.items.length : listing.scope.readable_files === 0 || !listing.items.length)"
            class="muted"
          >{{ keyword ? "没有匹配的文件" : "无可读取的文件" }}</p>

          <div v-if="listing && listing.count > 200" class="actions">
            <button type="button" :disabled="page === 1" @click="--page; refresh()">上一页</button>
            <span class="muted">{{ page }} / {{ Math.ceil(listing.count / 200) }}</span>
            <button type="button" :disabled="page * 200 >= listing.count" @click="++page; refresh()">下一页</button>
          </div>

          <details class="source-settings">
            <summary>公司归属、缓存与高级操作</summary>
            <p class="muted">归属仅作来源标注；公司、做账、税费等模块尚未接入，不计入其统计。</p>
            <p class="muted path">服务器源目录：{{ source.root }}</p>
            <p class="muted">本机缓存与汇总位于应用私有目录 `server-sources/`，共 {{ source.entry_count }} 项，已缓存 {{ source.cached_count }} 个文件。</p>
            <label class="field">
              公司
              <select v-model="company">
                <option value="">未归属</option>
                <option v-for="c in companies.companies" :key="c.id" :value="c.id">{{ c.name }}</option>
              </select>
            </label>
            <label class="field">
              角色
              <select v-model="role">
                <option value="cost_invoice_dir">进项发票</option>
                <option value="issued_invoice_dir">销项发票</option>
              </select>
            </label>
            <label class="field">
              副本预算（MiB）
              <input v-model.number="budget" type="number" min="64" max="10240">
            </label>
            <div class="actions">
              <button type="button" :disabled="!!running || busy" @click="saveSettings">保存设置</button>
              <button type="button" :disabled="!!running || busy" @click="clearCache">清除离线副本</button>
              <button type="button" class="ghost" :disabled="!!running || source.connection !== 'online' || busy" @click="start('summary', { parent_id: parent, verify: true })">校验内容</button>
              <button type="button" class="ghost" :disabled="!!running || source.connection !== 'online' || busy" @click="start('summary', { parent_id: parent, full: true })">完整重建</button>
              <button type="button" class="ghost" :disabled="!!running || busy" @click="forget">移除收藏</button>
            </div>
          </details>
        </template>

        <!-- Single-file preview tab -->
        <section v-else class="source-preview-tab" aria-label="服务器文件预览">
          <div v-if="preview" class="source-preview-tab__head">
            <p class="muted" role="status">
              {{ preview.stale ? "离线副本（可能过期）" : "已校验副本" }} · 最后核验 {{ preview.verified_at }}
            </p>
            <button type="button" class="ghost" @click="activateDirectoryTab">返回目录</button>
          </div>
          <p v-if="!preview && running" class="muted" aria-busy="true">正在按需下载并准备原票预览…</p>
          <template v-else-if="preview">
            <pre v-if="preview.preview_type === 'text'" class="source-preview-tab__text">{{ text }}</pre>
            <template v-else-if="preview.preview_type === 'pages'">
              <div v-if="preview.page_count > 1" class="actions">
                <button type="button" :disabled="previewPage <= 1" @click="error = ''; --previewPage">上一页</button>
                <span class="muted">{{ previewPage }} / {{ preview.page_count }}</span>
                <button type="button" :disabled="previewPage >= preview.page_count" @click="error = ''; ++previewPage">下一页</button>
              </div>
              <img
                class="source-preview-tab__img"
                :src="`/api/v1/sources/${selected}/previews/${preview.job_id}/pages/${previewPage}`"
                alt="服务器文件预览"
                @error="onPreviewImageError"
              >
            </template>
            <p v-else class="muted">{{ preview.reason }}</p>
          </template>
        </section>
      </template>
    </div>

    <footer v-if="source" class="server-panel__footer muted">
      <span>{{ PHASE_LABELS[source.sync] ?? source.sync }}</span>
      <span v-if="source.snapshot !== 'none'"> · 清单截至 {{ source.last_complete_at }}</span>
      <span> · 只读不写服务器</span>
    </footer>
  </aside>
</template>

<style scoped>
.server-panel {
  position: absolute;
  z-index: 35;
  inset: 0 0 0 auto;
  width: min(560px, 100%);
  max-width: 100%;
  background: var(--surface);
  border-left: 1px solid var(--line);
  box-shadow: -10px 0 32px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  color: var(--text);
}
.server-panel--wide { width: 100%; }
.server-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  flex: none;
}
.server-panel__title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.server-panel__title strong { display: block; font-size: 14px; }
.server-panel__title small { font-weight: 400; color: var(--muted); font-size: 11.5px; }
.server-panel__sub { margin: 0; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.server-panel__controls { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.server-picker-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}
.server-picker-bar__select { flex: 1; min-width: 0; margin: 0; }
.server-picker-bar__select select { width: 100%; height: 32px; }
.server-path-bar {
  padding: 8px 14px;
  border-bottom: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: none;
}
.breadcrumbs { display: flex; flex-wrap: wrap; gap: 2px; font-size: 12.5px; }
.breadcrumbs button { border: 0; background: transparent; padding: 2px 4px; height: auto; color: var(--text); font-weight: 600; }
.breadcrumbs button:hover { background: var(--surface-2); }
.server-path-bar__meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.subdir-picker { margin: 0; }
.subdir-picker select { height: 28px; font-size: 12px; max-width: 190px; }
.server-tabs {
  display: flex;
  overflow-x: auto;
  gap: 2px;
  padding: 6px 10px 0;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}
.server-tab {
  position: relative;
  display: flex;
  align-items: center;
  border: 1px solid transparent;
  border-bottom: 0;
  border-radius: 6px 6px 0 0;
  white-space: nowrap;
}
.server-tab.is-active {
  background: var(--surface);
  border-color: var(--line);
}
.server-tab > button:first-child {
  display: flex;
  align-items: center;
  gap: 6px;
  border: 0;
  background: transparent;
  padding: 6px 10px;
  height: 32px;
  font-size: 12.5px;
  font-weight: 600;
}
.server-tab__close {
  border: 0;
  background: transparent;
  padding: 2px 6px 2px 2px;
  height: auto;
  color: var(--muted);
}
.server-tab__line {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2.5px;
  background: #2778e5;
  transition: width 0.2s ease;
}
.server-tab__line.is-indeterminate { width: 40%; }
.server-body { flex: 1; overflow: auto; padding: 14px; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.server-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.summary-card {
  padding: 12px;
  border: 1px solid var(--ws-active-line);
  border-left: 3px solid var(--ws-lime-deep);
  border-radius: 4px;
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.summary-card__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.summary-card__head strong { font-size: 13.5px; }
.summary-card__head p, .summary-card__meta { margin: 0; font-size: 12px; }
.filter { display: flex; gap: 8px; }
.filter input { flex: 1; min-width: 0; }
.server-files { list-style: none; padding: 0; margin: 0; border-top: 1px solid var(--line); }
.server-files button {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  padding: 9px 6px;
  height: auto;
  text-align: left;
  background: transparent;
}
.server-files button:hover:not(:disabled) { background: var(--surface-2); }
.server-files__name { display: flex; align-items: center; gap: 7px; min-width: 0; overflow-wrap: anywhere; font-size: 13px; }
.server-files small { white-space: nowrap; color: var(--muted); font-size: 12px; }
.source-progress { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 4px; background: var(--surface-2); }
.source-progress__row { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 12.5px; }
.source-progress progress { width: 100%; height: 4px; accent-color: #2778e5; }
.fingerprints, .source-settings { padding: 10px 12px; border: 1px solid var(--line); border-radius: 4px; display: flex; flex-direction: column; gap: 8px; }
.fingerprint-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.source-settings summary { cursor: pointer; font-weight: 600; font-size: 13px; }
.source-preview-tab { display: flex; flex-direction: column; gap: 10px; }
.source-preview-tab__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.source-preview-tab__head p { margin: 0; font-size: 12px; }
.source-preview-tab__img { max-width: 100%; background: #fff; border: 1px solid var(--line); border-radius: 4px; }
.source-preview-tab__text { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 4px; background: var(--surface-2); margin: 0; }
.server-panel__footer { padding: 8px 14px; border-top: 1px solid var(--line); background: var(--surface-2); font-size: 12px; flex: none; }
</style>
