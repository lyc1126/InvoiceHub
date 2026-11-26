<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { request } from "../api/client";
import type { Company, FileMovePlanPayload } from "../api/types";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

// Confirmed cross-directory file move modal (WS-12).
// Always runs preview -> durable plan -> explicit confirm; if the confirm response is lost,
// queries GET .../files/move/{job_id} read-only instead of replaying the move.
const props = defineProps<{
  company: Company;
  dirKey: string;
  relativePaths: string[];
}>();
const emit = defineEmits<{ close: []; moved: [plan: FileMovePlanPayload] }>();

const companies = useCompaniesStore();
const targetCompanyId = ref(props.company.id);
const targetDirKey = ref("");
const targetSubpath = ref("");
const conflictPolicy = ref<"reject" | "rename">("reject");

const previewing = ref(false);
const confirming = ref(false);
const checkingJob = ref(false);
const error = ref("");
const plan = ref<FileMovePlanPayload | null>(null);
const lostResponseJobId = ref("");

const receiptLocked = computed(
  () => previewing.value || confirming.value || Boolean(lostResponseJobId.value) || Boolean(plan.value && plan.value.status !== "prepared"),
);
let previewGen = 0;

const targetCompany = computed(() =>
  companies.companies.find((item) => item.id === targetCompanyId.value) ?? props.company,
);

const availableTargetDirs = computed(() =>
  (targetCompany.value.subdirs ?? []).filter(
    (sub) =>
      sub.status === "present"
      && !sub.hidden
      && !(targetCompany.value.id === props.company.id && sub.key === props.dirKey && !targetSubpath.value.trim()),
  ),
);

watch(
  availableTargetDirs,
  (list) => {
    if (!list.some((item) => item.key === targetDirKey.value)) {
      targetDirKey.value = list[0]?.key ?? "";
    }
  },
  { immediate: true },
);

watch([targetCompanyId, targetDirKey, targetSubpath, conflictPolicy], () => {
  ++previewGen;
  previewing.value = false;
  plan.value = null;
  lostResponseJobId.value = "";
  error.value = "";
});

async function buildPreview(): Promise<void> {
  if (!targetDirKey.value || !props.relativePaths.length || previewing.value) return;
  const gen = ++previewGen;
  previewing.value = true;
  error.value = "";
  plan.value = null;
  try {
    const res = await request<FileMovePlanPayload>(
      `/api/v1/companies/${encodeURIComponent(props.company.id)}/directories/${encodeURIComponent(props.dirKey)}/files/move/preview`,
      {
        method: "POST",
        body: {
          conflict_policy: conflictPolicy.value,
          items: props.relativePaths.map((relative_path) => ({
            relative_path,
            target_company_id: targetCompanyId.value,
            target_dir_key: targetDirKey.value,
            target_subpath: targetSubpath.value.trim(),
          })),
        },
      },
    );
    if (gen !== previewGen) return;
    plan.value = res;
  } catch (cause) {
    if (gen !== previewGen) return;
    error.value = errorText(cause);
  } finally {
    if (gen === previewGen) {
      previewing.value = false;
    }
  }
}

async function confirmMove(): Promise<void> {
  const active = plan.value;
  if (!active || !active.can_confirm || confirming.value) return;
  confirming.value = true;
  error.value = "";
  lostResponseJobId.value = "";
  try {
    const res = await request<FileMovePlanPayload>(
      `/api/v1/companies/${encodeURIComponent(props.company.id)}/directories/${encodeURIComponent(props.dirKey)}/files/move/${encodeURIComponent(active.job_id)}/confirm`,
      {
        method: "POST",
        body: { confirm: true, plan_hash: active.plan_hash },
      },
    );
    plan.value = res;
    if (res.status !== "completed" || (res.failed ?? 0) > 0 || (res.unknown ?? 0) > 0 || (res.pending ?? 0) > 0) {
      error.value = `部分文件未完成移动（已移动 ${res.moved ?? 0}，失败 ${res.failed ?? 0}，待核对 ${res.unknown ?? 0}，未执行 ${res.pending ?? 0}）；请核对下方逐文件回执。`;
    }
    toast(`移动完成：成功 ${res.moved ?? 0} 个${res.failed ? `，失败 ${res.failed} 个` : ""}。`, res.failed ? "error" : "info", 4500);
    emit("moved", res);
  } catch (cause) {
    lostResponseJobId.value = active.job_id;
    error.value = `${errorText(cause)}（请先查询本次移动结果，切勿盲目重试。）`;
  } finally {
    confirming.value = false;
  }
}

async function checkLostJob(): Promise<void> {
  if (!lostResponseJobId.value || checkingJob.value) return;
  checkingJob.value = true;
  error.value = "";
  try {
    const res = await request<FileMovePlanPayload>(
      `/api/v1/companies/${encodeURIComponent(props.company.id)}/directories/${encodeURIComponent(props.dirKey)}/files/move/${encodeURIComponent(lostResponseJobId.value)}`,
    );
    plan.value = res;
    if (res.status === "completed" || res.status === "partial") {
      lostResponseJobId.value = "";
      if (res.status !== "completed" || (res.failed ?? 0) > 0 || (res.unknown ?? 0) > 0) {
        error.value = `部分文件未完成移动（已移动 ${res.moved ?? 0}，失败 ${res.failed ?? 0}，待核对 ${res.unknown ?? 0}，未执行 ${res.pending ?? 0}）；请核对下方逐文件回执。`;
      }
      emit("moved", res);
    } else if (res.status === "running") {
      error.value = "该移动任务仍在执行或上次中断，请核对下方逐文件回执，切勿重复确认。";
    }
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    checkingJob.value = false;
  }
}
</script>

<template>
  <WsModal
    title="移动到其他目录"
    :subtitle="`已选 ${relativePaths.length} 个文件；先预览计划，确认后执行且绝不覆盖同名文件。`"
    :wide="true"
    :closable="!confirming && !checkingJob"
    @close="!confirming && !checkingJob && emit('close')"
  >
    <div class="move-modal">
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <div class="move-modal__controls">
        <label>
          <span>目标公司</span>
          <select v-model="targetCompanyId" aria-label="移动目标公司" :disabled="receiptLocked">
            <option v-for="c in companies.companies" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
        <label>
          <span>目标目录</span>
          <select v-model="targetDirKey" aria-label="移动目标目录" :disabled="receiptLocked || !availableTargetDirs.length">
            <option v-for="sub in availableTargetDirs" :key="sub.key" :value="sub.key">
              {{ sub.label }}{{ sub.kind === "custom" ? `（${sub.role_label || "普通资料"}）` : "" }}
            </option>
          </select>
        </label>
        <label>
          <span>目标子路径（可选）</span>
          <input v-model="targetSubpath" type="text" placeholder="留空放到目录根，如 2026-11" aria-label="移动目标子路径" :disabled="receiptLocked">
        </label>
        <label>
          <span>同名冲突策略</span>
          <select v-model="conflictPolicy" aria-label="同名冲突策略" :disabled="receiptLocked">
            <option value="reject">遇同名拒绝覆盖（推荐）</option>
            <option value="rename">遇同名自动追加序号重命名</option>
          </select>
        </label>
      </div>

      <div class="actions">
        <button type="button" :disabled="previewing || receiptLocked || !targetDirKey" :aria-busy="previewing" @click="buildPreview">
          {{ previewing ? "生成计划中…" : "预览移动计划" }}
        </button>
        <button v-if="lostResponseJobId" type="button" :disabled="checkingJob" @click="checkLostJob">
          {{ checkingJob ? "查询中…" : "查询本次移动结果" }}
        </button>
      </div>

      <div v-if="plan" class="move-modal__plan">
        <p class="muted">
          计划摘要：正常移动 {{ plan.summary.move }} · 自动改名 {{ plan.summary.rename }} · 冲突 {{ plan.summary.conflict }} · 受阻 {{ plan.summary.blocked }}
        </p>
        <table class="grid" aria-label="移动文件计划">
          <thead>
            <tr>
              <th>原文件</th>
              <th>目标位置</th>
              <th>处理方式</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in plan.items" :key="item.relative_path" :class="{ 'row--danger': item.action === 'conflict' || item.action === 'blocked' }">
              <td class="path mono">{{ item.relative_path }}</td>
              <td class="path mono">{{ item.target_company_name }} / {{ item.target_dir_label }}{{ item.target_subpath ? `/${item.target_subpath}` : "" }} / {{ item.target_name }}</td>
              <td>
                <span v-if="item.action === 'move'">正常移动</span>
                <span v-else-if="item.action === 'rename'">{{ item.reason }}</span>
                <strong v-else class="check--failed">{{ item.reason }}</strong>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="plan?.results?.length" class="move-modal__plan">
        <p class="muted">
          执行回执（状态：{{ plan.status }}）：已移动 {{ plan.moved ?? 0 }} · 失败 {{ plan.failed ?? 0 }} · 待核对 {{ plan.unknown ?? 0 }} · 未执行 {{ plan.pending ?? 0 }}
        </p>
        <table class="grid" aria-label="移动执行结果">
          <thead>
            <tr>
              <th>原文件</th>
              <th>目标文件名</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="res in plan.results" :key="res.relative_path" :class="{ 'row--danger': res.status === 'failed' || res.status === 'unknown' || res.status === 'moving' }">
              <td class="path mono">{{ res.relative_path }}</td>
              <td class="path mono">{{ res.target_name }}</td>
              <td>{{ res.message || res.status }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="actions">
        <button
          v-if="plan && plan.status === 'prepared' && !lostResponseJobId"
          type="button"
          class="primary"
          :disabled="!plan.can_confirm || confirming"
          :aria-busy="confirming"
          @click="confirmMove"
        >
          {{ confirming ? "移动中…" : `确认移动 ${plan.items.length} 个文件` }}
        </button>
        <button type="button" :disabled="confirming || checkingJob" @click="emit('close')">关闭</button>
      </div>
    </div>
  </WsModal>
</template>

<style scoped>
.move-modal { display: grid; gap: 12px; }
.move-modal__controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px 12px; }
.move-modal__controls label { display: grid; gap: 4px; font-size: 13px; }
.move-modal__plan { display: grid; gap: 8px; max-height: 36vh; overflow: auto; }
</style>
