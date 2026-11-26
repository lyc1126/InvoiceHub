<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError } from "../api/client";
import type { Company, CompanyFolderTrashPlan, CompanySubdir } from "../api/types";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

const props = defineProps<{ company: Company; subdir: CompanySubdir }>();
const emit = defineEmits<{ close: []; done: [payload: { key: string; removedFromList: boolean; trashed: boolean }] }>();

const companies = useCompaniesStore();
const isCustom = computed(() => props.subdir.kind === "custom");
const mode = ref<"unregister" | "trash">("unregister");
const loadingPlan = ref(false);
const busy = ref(false);
const error = ref("");
const trashPlan = ref<CompanyFolderTrashPlan | null>(null);
const confirmedTrash = ref(false);
const alsoUnregister = ref(props.subdir.kind === "custom");

let generation = 0;
onBeforeUnmount(() => { ++generation; });

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

async function loadTrashPlan(): Promise<void> {
  const mine = ++generation;
  loadingPlan.value = true;
  error.value = "";
  confirmedTrash.value = false;
  try {
    const plan = await companies.previewTrashFolder(props.company.id, props.subdir.key);
    if (mine === generation) trashPlan.value = plan;
  } catch (cause) {
    if (mine === generation) {
      error.value = errorText(cause);
      trashPlan.value = null;
    }
  } finally {
    if (mine === generation) loadingPlan.value = false;
  }
}

watch(mode, (value) => {
  error.value = "";
  if (value === "trash") void loadTrashPlan();
});

async function submitUnregister(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await companies.removeFolder(props.company.id, props.subdir.key);
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    toast(
      isCustom.value
        ? `已从列表移除「${props.subdir.label}」（硬盘文件未改动）`
        : `已隐藏默认文件夹「${props.subdir.label}」（硬盘文件未改动，随时可恢复）`,
      "info",
      3400,
    );
    emit("done", { key: props.subdir.key, removedFromList: true, trashed: false });
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

async function submitTrash(): Promise<void> {
  if (!trashPlan.value?.can_trash || !confirmedTrash.value || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await companies.trashFolder(props.company.id, props.subdir.key, {
      plan_hash: trashPlan.value.plan_hash,
      also_unregister: alsoUnregister.value,
    });
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    toast(`已将「${props.subdir.label}」移入系统回收站 / 废纸篓`, "info", 3600);
    emit("done", { key: props.subdir.key, removedFromList: result.unregistered, trashed: true });
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.code === "COMPANY_PLAN_STALE"
      ? "文件夹状态已变化，请重新核对预览后再确认。"
      : errorText(cause);
    if (cause instanceof ApiError && cause.code === "COMPANY_PLAN_STALE") void loadTrashPlan();
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <WsModal
    :title="`移除或删除文件夹 · ${subdir.label}`"
    :subtitle="`${company.name} · 请明确选择「仅移除登记」或「移入系统回收站」`"
    @close="!busy && emit('close')"
  >
    <div class="folder-delete-body">
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <div class="folder-mode-list" role="radiogroup" aria-label="删除方式">
        <label class="panel folder-mode-card" :class="{ 'folder-mode-card--active': mode === 'unregister' }">
          <input v-model="mode" type="radio" value="unregister" :disabled="busy">
          <div>
            <strong>{{ isCustom ? "仅从工作区列表移除（推荐，不删文件）" : "仅从侧栏隐藏此默认文件夹（不删文件）" }}</strong>
            <p class="muted">{{ isCustom ? "只取消本软件对该文件夹的登记，硬盘上的文件夹和文件一个都不会动。" : "隐藏后侧栏不再显示该槽位，硬盘上的文件夹和文件保留；随时可在「管理文件夹」恢复显示。" }}</p>
          </div>
        </label>

        <label class="panel folder-mode-card" :class="{ 'folder-mode-card--active': mode === 'trash' }">
          <input v-model="mode" type="radio" value="trash" :disabled="busy || subdir.status !== 'present'">
          <div>
            <strong>将硬盘上的文件夹移入系统回收站 / 废纸篓</strong>
            <p class="muted">调用系统原生回收站/废纸篓移动整个文件夹（绝不永久删除，可在回收站恢复）；正在监控的目录需先切换监控。</p>
          </div>
        </label>
      </div>

      <template v-if="mode === 'unregister'">
        <p class="muted path mono">文件夹路径：{{ subdir.path }}</p>
        <div class="actions">
          <button type="button" class="primary" :disabled="busy" :aria-busy="busy" @click="submitUnregister">
            {{ busy ? "处理中…" : isCustom ? "确认仅移除登记" : "确认隐藏" }}
          </button>
          <button type="button" class="ghost" :disabled="busy" @click="emit('close')">取消</button>
        </div>
      </template>

      <template v-else>
        <p v-if="loadingPlan" class="muted" role="status" aria-busy="true">正在核对文件夹路径与内容统计…</p>
        <template v-else-if="trashPlan">
          <div class="panel folder-trash-summary">
            <p><strong>硬盘路径：</strong><span class="path mono">{{ trashPlan.path }}</span></p>
            <p>
              <strong>当前内容：</strong>
              {{ trashPlan.truncated ? `至少 ${trashPlan.file_count}` : trashPlan.file_count }} 个文件、{{ trashPlan.dir_count }} 个子目录（共 {{ formatBytes(trashPlan.total_bytes) }}）
            </p>
            <p v-if="trashPlan.is_external" class="overview-notice overview-notice--warn">
              <span><strong>注意：</strong>这是公司资料夹之外的外部导入文件夹，移入系统回收站会直接影响原位置的文件。</span>
            </p>
            <p v-if="!trashPlan.can_trash" class="banner banner--error" role="alert">{{ trashPlan.blocked_reason }}</p>
          </div>

          <template v-if="trashPlan.can_trash">
            <label class="folder-check-row">
              <input v-model="alsoUnregister" type="checkbox" :disabled="busy">
              <span>{{ isCustom ? "移入回收站后同时从工作区列表移除" : "移入回收站后同时隐藏该默认槽位（不勾选则保留为「缺失」，方便之后重建）" }}</span>
            </label>
            <label class="folder-check-row folder-check-row--danger">
              <input v-model="confirmedTrash" type="checkbox" :disabled="busy">
              <span>我已核对路径，确认将该文件夹移入系统回收站 / 废纸篓（绝不执行永久删除）</span>
            </label>
            <div class="actions">
              <button type="button" class="danger-fill" :disabled="busy || !confirmedTrash" :aria-busy="busy" @click="submitTrash">
                {{ busy ? "移入回收站中…" : "确认移入系统回收站" }}
              </button>
              <button type="button" class="ghost" :disabled="busy" @click="emit('close')">取消</button>
            </div>
          </template>
          <div v-else class="actions">
            <button type="button" class="ghost" @click="emit('close')">关闭</button>
          </div>
        </template>
      </template>
    </div>
  </WsModal>
</template>

<style scoped>
.folder-delete-body { display: grid; gap: 12px; }
.folder-mode-list { display: grid; gap: 8px; }
.folder-mode-card { display: flex; align-items: flex-start; gap: 10px; padding: 12px; cursor: pointer; }
.folder-mode-card--active { border-color: var(--ws-active-line); background: var(--ws-selected); }
.folder-mode-card p { margin: 4px 0 0; font-size: 12.5px; }
.folder-trash-summary { padding: 12px; display: grid; gap: 8px; font-size: 13px; }
.folder-trash-summary p { margin: 0; }
.folder-check-row { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; cursor: pointer; }
.folder-check-row--danger { font-weight: 600; color: var(--red); }
</style>
