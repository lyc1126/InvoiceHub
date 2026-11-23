<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { ProjectRenamePreview, ProjectRenameResult } from "../api/types";
import { errorText } from "../format";
import WsModal from "./WsModal.vue";

// Preview-then-confirm project rename (WS-03): updates manual overrides, saves a 1-hop remark
// alias in 项目归属.json, and optionally syncs linked 服务成本归集.json rows without modifying source files.
const props = defineProps<{
  companyId: string;
  companyName?: string;
  fromName: string;
  revision: number;
  projectNames: string[];
}>();
const emit = defineEmits<{ close: []; done: [result: ProjectRenameResult] }>();

const toName = ref(props.fromName);
const syncServiceCosts = ref(true);
const preview = ref<ProjectRenamePreview | null>(null);
const previewing = ref(false);
const saving = ref(false);
const error = ref("");
const base = computed(() => `/api/v1/companies/${encodeURIComponent(props.companyId)}/projects`);
const otherNames = computed(() => props.projectNames.filter((name) => name && name !== props.fromName));
const trimmedTo = computed(() => toName.value.trim().replace(/\s+/g, " "));
const canPreview = computed(() => !!trimmedTo.value && trimmedTo.value !== props.fromName && !previewing.value && !saving.value);

watch([toName, syncServiceCosts], () => {
  // Any input edit invalidates the old preview_hash so the user re-checks before confirming.
  preview.value = null;
  error.value = "";
});

async function runPreview(): Promise<void> {
  if (!canPreview.value) return;
  previewing.value = true;
  error.value = "";
  try {
    preview.value = await request<ProjectRenamePreview>(`${base.value}/rename/preview`, {
      method: "POST",
      body: {
        revision: props.revision,
        from_name: props.fromName,
        to_name: trimmedTo.value,
        sync_service_costs: syncServiceCosts.value,
      },
    });
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.code === "COMPANY_PROJECTS_CONFLICT"
      ? "项目归属已更新，请关闭弹窗并刷新页面后重试。"
      : errorText(cause);
  } finally {
    previewing.value = false;
  }
}

async function confirmRename(): Promise<void> {
  if (!preview.value || saving.value) return;
  saving.value = true;
  error.value = "";
  try {
    const result = await request<ProjectRenameResult>(`${base.value}/rename`, {
      method: "POST",
      body: {
        revision: preview.value.revision,
        from_name: preview.value.from_name,
        to_name: preview.value.to_name,
        sync_service_costs: preview.value.sync_service_costs,
        service_costs_revision: preview.value.service_costs_revision,
        preview_hash: preview.value.preview_hash,
        confirm: true,
      },
    });
    emit("done", result);
  } catch (cause) {
    preview.value = null;
    error.value = cause instanceof ApiError && cause.code === "COMPANY_PROJECTS_CONFLICT"
      ? "项目归属或服务成本在预览后已变化，请重新预览再确认。"
      : errorText(cause);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <WsModal
    :title="`重命名项目 · ${fromName}`"
    :subtitle="`${companyName ? `${companyName} · ` : ''}只更新公司项目归属与重命名映射，不改动任何源发票文件。`"
    @close="!saving && emit('close')"
  >
    <form class="stack" @submit.prevent="preview ? confirmRename() : runPreview()">
      <label class="field">
        新项目名称
        <input
          v-model="toName"
          type="text"
          maxlength="60"
          list="project-rename-suggestions"
          placeholder="输入新的项目名称（可输入已有项目名合并）"
          aria-label="新项目名称"
          :disabled="saving || previewing"
        >
      </label>
      <datalist id="project-rename-suggestions">
        <option v-for="name in otherNames" :key="name" :value="name" />
      </datalist>
      <label class="checkbox-inline">
        <input v-model="syncServiceCosts" type="checkbox" :disabled="saving || previewing">
        同步更新成本分析中同一项目的服务成本记录
      </label>
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <div v-if="preview" class="panel" role="status" aria-label="重命名影响预览">
        <p>
          将把 <strong>{{ preview.from_name }}</strong> 重命名为 <strong>{{ preview.to_name }}</strong>：
          影响 <strong>{{ preview.total_invoices }}</strong> 张发票（人工指定 {{ preview.manual_count }} 张，备注自动映射 {{ preview.remark_count }} 张）。
        </p>
        <p v-if="preview.merges_into_existing" class="banner banner--note">
          「{{ preview.to_name }}」已存在，确认后两个项目的发票将合并汇总。
        </p>
        <p v-if="preview.service_cost_count > 0" class="muted">
          {{ preview.sync_service_costs
            ? `同时更新 ${preview.service_cost_count} 条关联的服务成本记录。`
            : `检测到 ${preview.service_cost_count} 条关联的服务成本记录（未勾选同步，将保留原项目名）。` }}
        </p>
      </div>

      <div class="actions">
        <button v-if="!preview" type="submit" class="primary" :disabled="!canPreview" :aria-busy="previewing">
          {{ previewing ? "预览中…" : "预览影响" }}
        </button>
        <button v-else type="submit" class="primary" :disabled="saving" :aria-busy="saving">
          {{ saving ? "保存中…" : "确认重命名" }}
        </button>
        <button type="button" class="ghost" :disabled="saving" @click="emit('close')">取消</button>
      </div>
    </form>
  </WsModal>
</template>
