<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { request } from "../api/client";
import { errorText } from "../format";
import { CONNECTION_LABELS, type MountedShare, type ServerSource, useSourcesStore } from "../stores/sources";
import WsModal from "./WsModal.vue";
import WorkspaceIcon from "./WorkspaceIcon.vue";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{
  close: [];
  connected: [sourceId: string];
}>();

const store = useSourcesStore();
const protocol = ref<"mounted" | "sftp">("mounted");
const name = ref("");
const root = ref("");
const host = ref("");
const port = ref(22);
const username = ref("");
const busy = ref(false);
const error = ref("");
const smbHint = ref("");

const favorites = computed(() => store.sources.filter((item) => item.protocol === protocol.value));

function resetForm(nextProtocol: "mounted" | "sftp" = protocol.value): void {
  protocol.value = nextProtocol;
  name.value = "";
  root.value = "";
  host.value = "";
  port.value = 22;
  username.value = "";
  error.value = "";
  smbHint.value = "";
}

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    error.value = "";
    smbHint.value = "";
    void store.load();
    void store.loadMountedShares();
  },
  { immediate: true },
);

function selectShare(share: MountedShare): void {
  protocol.value = "mounted";
  root.value = share.path;
  if (!name.value.trim()) name.value = share.name;
  error.value = "";
  smbHint.value = share.remote ? `已选择系统挂载卷：${share.remote}` : "";
}

function onRootInput(): void {
  smbHint.value = "";
  const raw = root.value.trim();
  if (!raw.toLowerCase().startsWith("smb://")) return;
  const shareName = raw.split("/").filter(Boolean).at(-1)?.toLowerCase() ?? "";
  const matched = store.mountedShares.find(
    (share) =>
      share.remote.toLowerCase().includes(shareName) ||
      share.name.toLowerCase() === shareName,
  );
  if (matched) {
    smbHint.value = `检测到系统已挂载此共享：${matched.path}，点击下方已挂载卷卡片即可一键填入。`;
  } else {
    smbHint.value = "SMB 共享需先在系统（访达 ⌘K 或 Windows 映射网络驱动器）挂载，再点击「选择目录」或下方已挂载卷填入本地挂载路径。";
  }
}

async function pickDirectory(): Promise<void> {
  error.value = "";
  busy.value = true;
  try {
    const result = await request<{ path?: string; selected_path?: string }>("/api/v1/sources/pick", {
      method: "POST",
      body: {},
    });
    const chosen = result.path ?? result.selected_path ?? "";
    if (chosen) {
      root.value = chosen;
      if (!name.value.trim()) {
        name.value = chosen.split(/[\\/]/).filter(Boolean).at(-1) ?? "共享目录";
      }
      smbHint.value = "";
    }
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

async function openExisting(source: ServerSource): Promise<void> {
  store.selectedId = source.id;
  emit("connected", source.id);
  emit("close");
}

async function removeFavorite(source: ServerSource): Promise<void> {
  if (!window.confirm(`移除「${source.name}」的收藏和本机缓存？服务器文件不会改动。`)) return;
  error.value = "";
  busy.value = true;
  try {
    await request(`/api/v1/sources/${source.id}?revision=${source.revision}`, { method: "DELETE" });
    store.remove(source.id);
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

async function submitAdd(): Promise<void> {
  error.value = "";
  busy.value = true;
  try {
    const payload =
      protocol.value === "mounted"
        ? { protocol: "mounted", name: name.value.trim(), root: root.value.trim() }
        : {
            protocol: "sftp",
            name: name.value.trim(),
            root: root.value.trim(),
            host: host.value.trim(),
            port: Number(port.value),
            username: username.value.trim(),
          };
    const result = await request<{ source: ServerSource }>("/api/v1/sources", {
      method: "POST",
      body: payload,
    });
    store.upsert(result.source);
    store.selectedId = result.source.id;
    // Newly-added mounted SMB shares scan immediately; SFTP probes host keys so
    // the user can verify and confirm the fingerprint without extra clicks.
    const initialTask = result.source.protocol === "mounted" ? "scan" : "probe";
    try {
      const started = await request<{ source: ServerSource }>(`/api/v1/sources/${result.source.id}/tasks`, {
        method: "POST",
        body: { kind: initialTask },
      });
      store.upsert(started.source);
    } catch {
      // Keep the saved source open in the panel so the user can inspect or retry.
    }
    resetForm(protocol.value);
    emit("connected", result.source.id);
    emit("close");
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <WsModal
    :open="open"
    title="服务器链接（试验版）"
    subtitle="只读访问局域网 SMB 共享目录或 SFTP 服务器；不写入服务器，不切换活动监控目录。"
    @close="emit('close')"
  >
    <div class="server-connect">
      <div class="period-segment" role="tablist" aria-label="连接协议">
        <button
          type="button"
          role="tab"
          :aria-selected="protocol === 'mounted'"
          :class="{ active: protocol === 'mounted' }"
          @click="protocol = 'mounted'; error = ''"
        >共享文件夹 (SMB)</button>
        <button
          type="button"
          role="tab"
          :aria-selected="protocol === 'sftp'"
          :class="{ active: protocol === 'sftp' }"
          @click="protocol = 'sftp'; error = ''"
        >SSH / SFTP</button>
      </div>

      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <section v-if="favorites.length" class="connect-section" aria-label="个人收藏来源">
        <div class="connect-section__head">
          <h4>个人收藏来源</h4>
          <span class="muted">点击直接打开右侧目录浏览</span>
        </div>
        <div class="favorite-list">
          <div v-for="item in favorites" :key="item.id" class="favorite-row">
            <button type="button" class="favorite-row__main" @click="openExisting(item)">
              <WorkspaceIcon name="server" />
              <span class="favorite-row__info">
                <strong>{{ item.name }}</strong>
                <small class="path">{{ item.root }}</small>
              </span>
              <span class="tag" :class="item.connection === 'online' ? 'pill-ok' : ''">{{ CONNECTION_LABELS[item.connection] ?? item.connection }}</span>
            </button>
            <button
              type="button"
              class="ghost"
              :disabled="busy"
              :aria-label="`移除收藏 ${item.name}`"
              @click="removeFavorite(item)"
            >移除</button>
          </div>
        </div>
      </section>

      <section v-if="protocol === 'mounted'" class="connect-section" aria-label="系统已挂载共享">
        <div class="connect-section__head">
          <h4>系统已挂载共享</h4>
          <button type="button" class="ghost" :disabled="store.sharesLoading" @click="store.loadMountedShares()">
            {{ store.sharesLoading ? "扫描中…" : "刷新挂载列表" }}
          </button>
        </div>
        <div v-if="store.mountedShares.length" class="share-chips">
          <button
            v-for="share in store.mountedShares"
            :key="share.path"
            type="button"
            class="share-chip"
            :class="{ 'is-selected': root === share.path }"
            @click="selectShare(share)"
          >
            <WorkspaceIcon name="folder" />
            <span>
              <strong>{{ share.name }}</strong>
              <small class="path">{{ share.path }}</small>
            </span>
          </button>
        </div>
        <p v-else class="muted">未发现系统已挂载的网络共享卷；你也可以在下方点击「选择目录」直接选取已挂载的共享路径或子文件夹。</p>
      </section>

      <form class="connect-form" @submit.prevent="submitAdd">
        <h4>{{ protocol === "mounted" ? "添加共享文件夹" : "添加 SSH / SFTP 连接" }}</h4>
        <label class="field">
          收藏名称
          <input v-model="name" required maxlength="100" :placeholder="protocol === 'mounted' ? '例如：财务共享盘 / 某项目发票' : '例如：远程资料库'">
        </label>
        <template v-if="protocol === 'sftp'">
          <div class="connect-grid">
            <label class="field">主机<input v-model="host" required placeholder="files.example.test（不含 sftp://）"></label>
            <label class="field">端口<input v-model.number="port" type="number" min="1" max="65535" required></label>
          </div>
          <label class="field">用户名<input v-model="username" required autocomplete="off"></label>
          <p class="overview-notice">仅支持已解锁 SSH Agent 的只读 SFTP（试验版），不保存密码或私钥；保存后将自动读取主机指纹供核对。</p>
        </template>
        <label class="field">
          {{ protocol === "mounted" ? "系统挂载目录" : "服务器根目录" }}
          <div class="path-input-row">
            <input
              v-model="root"
              required
              class="path"
              :placeholder="protocol === 'mounted' ? '/Volumes/共享名 或 \\\\server\\share' : '/invoices'"
              @input="onRootInput"
            >
            <button v-if="protocol === 'mounted'" type="button" :disabled="busy" @click="pickDirectory">选择目录</button>
          </div>
        </label>
        <p v-if="smbHint" class="overview-notice overview-notice--warn">{{ smbHint }}</p>
        <div class="connect-actions">
          <span class="muted">只读访问 · 原文件不改动</span>
          <div class="actions">
            <button type="button" class="ghost" @click="emit('close')">取消</button>
            <button type="submit" class="primary" :disabled="busy" :aria-busy="busy">{{ busy ? "保存中…" : "保存并打开" }}</button>
          </div>
        </div>
      </form>
    </div>
  </WsModal>
</template>

<style scoped>
.server-connect { display: flex; flex-direction: column; gap: 16px; }
.connect-section { display: flex; flex-direction: column; gap: 8px; }
.connect-section__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.connect-section__head h4, .connect-form h4 { margin: 0; font-size: 14px; font-weight: 700; }
.favorite-list { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.favorite-row { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-bottom: 1px solid var(--line); background: var(--surface); }
.favorite-row:last-child { border-bottom: 0; }
.favorite-row__main { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; border: 0; background: transparent; text-align: left; padding: 4px; height: auto; }
.favorite-row__main:hover { background: var(--surface-2); }
.favorite-row__info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.favorite-row__info strong { font-size: 13.5px; }
.favorite-row__info small { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.share-chips { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.share-chip { display: flex; align-items: center; gap: 8px; text-align: left; padding: 8px 10px; height: auto; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 4px; }
.share-chip.is-selected { border-color: var(--ws-active-line); background: var(--ws-selected); }
.share-chip span { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.share-chip strong { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.share-chip small { color: var(--muted); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.connect-form { display: flex; flex-direction: column; gap: 10px; padding-top: 12px; border-top: 1px solid var(--line); }
.connect-grid { display: grid; grid-template-columns: 1fr 110px; gap: 10px; }
.path-input-row { display: flex; gap: 8px; }
.path-input-row input { flex: 1; min-width: 0; }
.connect-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-top: 4px; }
</style>
