<script setup lang="ts">
import { ref, watch } from "vue";
import { ApiError } from "../api/client";
import type { Company, CompanyTrashPlan } from "../api/types";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

const props = defineProps<{ company: Company }>();
const emit = defineEmits<{ close: []; done: [result: { companyId: string; trashed: boolean }] }>();

const companies = useCompaniesStore();
const mode = ref<"unregister" | "trash">("unregister");
const loadingPlan = ref(false);
const busy = ref(false);
const error = ref("");
const trashPlan = ref<CompanyTrashPlan | null>(null);
const confirmedTrash = ref(false);
let generation = 0;

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
    const plan = await companies.previewTrashCompany(props.company.id);
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
    await companies.remove(props.company.id);
    toast(`已从工作区清单移除「${props.company.name}」（硬盘文件未改动）`, "info", 3400);
    emit("done", { companyId: props.company.id, trashed: false });
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
    await companies.trashCompany(props.company.id, trashPlan.value.plan_hash);
    toast(`已将「${props.company.name}」资料夹移入系统回收站 / 废纸篓并移出清单`, "info", 3800);
    emit("done", { companyId: props.company.id, trashed: true });
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.code === "COMPANY_PLAN_STALE"
      ? "公司资料夹状态已变化，请重新核对预览后再确认。"
      : errorText(cause);
    if (cause instanceof ApiError && cause.code === "COMPANY_PLAN_STALE") void loadTrashPlan();
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <WsModal
    :title="`移除或删除公司工作区 · ${company.name}`"
    subtitle="请选择「仅从清单移除」或「将公司资料夹移入系统回收站」"
    @close="!busy && emit('close')"
  >
    <div class="company-delete-body">
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <div class="company-mode-list" role="radiogroup" aria-label="公司移除方式">
        <label class="panel company-mode-card" :class="{ 'company-mode-card--active': mode === 'unregister' }">
          <input v-model="mode" type="radio" value="unregister" :disabled="busy">
          <div>
            <strong>仅从工作区清单移除（推荐，不删文件）</strong>
            <p class="muted">只取消本软件对这家公司的登记，硬盘上的公司资料夹及全部发票/文档一个都不会动；之后随时可以重新导入。</p>
          </div>
        </label>

        <label class="panel company-mode-card" :class="{ 'company-mode-card--active': mode === 'trash' }">
          <input v-model="mode" type="radio" value="trash" :disabled="busy || company.root_status !== 'present'">
          <div>
            <strong>将公司资料夹移入系统回收站 / 废纸篓并移出清单</strong>
            <p class="muted">适合刚建错或确认不再使用的资料夹。调用系统原生回收站/废纸篓移动（绝不永久删除，可在回收站恢复）；正在监控该公司目录时需先切换监控。</p>
          </div>
        </label>
      </div>

      <template v-if="mode === 'unregister'">
        <p class="muted path mono">资料夹路径：{{ company.root_path }}</p>
        <div class="actions">
          <button type="button" class="primary" :disabled="busy" :aria-busy="busy" @click="submitUnregister">
            {{ busy ? "移除中…" : "确认仅从清单移除" }}
          </button>
          <button type="button" class="ghost" :disabled="busy" @click="emit('close')">取消</button>
        </div>
      </template>

      <template v-else>
        <p v-if="loadingPlan" class="muted" role="status" aria-busy="true">正在核对公司资料夹路径与内容统计…</p>
        <template v-else-if="trashPlan">
          <div class="panel company-trash-summary">
            <p><strong>目标公司资料夹</strong></p>
            <p class="path mono">{{ trashPlan.path }}</p>
            <p v-if="!trashPlan.can_trash" class="banner banner--error" role="alert">{{ trashPlan.blocked_reason }}</p>
            <template v-else>
              <p class="muted">
                当前包含 <strong>{{ trashPlan.file_count }}</strong> 个文件、<strong>{{ trashPlan.dir_count }}</strong> 个子文件夹，合计约 <strong>{{ formatBytes(trashPlan.total_bytes) }}</strong><span v-if="trashPlan.truncated">（条目较多，仅统计前 5000 项）</span>。
              </p>
              <p v-if="trashPlan.external_folders.length" class="overview-notice overview-notice--warn">
                <span>该公司另外挂载了 {{ trashPlan.external_folders.length }} 个外部导入文件夹（{{ trashPlan.external_folders.map((item) => item.label).join("、") }}）；这些外部文件夹<strong>不会被删除</strong>，仅随公司解除登记。</span>
              </p>
              <label class="company-confirm-check">
                <input v-model="confirmedTrash" type="checkbox" :disabled="busy">
                <span>我已核对上方路径与文件数，确认将整个公司资料夹移入系统回收站 / 废纸篓并移出工作区清单</span>
              </label>
            </template>
          </div>
          <div class="actions">
            <button
              type="button"
              class="danger-fill"
              :disabled="busy || !trashPlan.can_trash || !confirmedTrash"
              :aria-busy="busy"
              @click="submitTrash"
            >
              {{ busy ? "移入回收站中…" : "确认移入回收站并移出清单" }}
            </button>
            <button type="button" class="ghost" :disabled="busy" @click="emit('close')">取消</button>
          </div>
        </template>
      </template>
    </div>
  </WsModal>
</template>

<style scoped>
.company-delete-body { display: grid; gap: 12px; }
.company-mode-list { display: grid; gap: 8px; }
.company-mode-card {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 10px;
  align-items: start;
  padding: 12px;
  cursor: pointer;
}
.company-mode-card--active { border-color: var(--ws-active-line); background: var(--ws-selected); }
.company-mode-card p { margin: 4px 0 0; font-size: 12.5px; }
.company-trash-summary { padding: 12px; display: grid; gap: 8px; font-size: 13px; }
.company-trash-summary p { margin: 0; }
.company-confirm-check { display: flex; gap: 8px; align-items: start; font-weight: 600; cursor: pointer; }
</style>
