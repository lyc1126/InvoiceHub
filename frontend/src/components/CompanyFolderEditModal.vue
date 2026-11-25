<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Company, CompanySubdir, FolderRole, FolderRoleMeta } from "../api/types";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

const DEFAULT_ROLES: FolderRoleMeta[] = [
  { key: "cost_invoice_dir", label: "成本发票", short_tag: "进项", description: "按进项/成本发票处理：一键读取、发票列表、监控预览、回收站删除与同号检查。" },
  { key: "issued_invoice_dir", label: "开具发票", short_tag: "销项", description: "按销项/开具发票处理：一键读取、发票列表、监控预览、回收站删除与同号检查。" },
  { key: "expense_reimbursement_dir", label: "费用报销", short_tag: "报销", description: "按费用报销发票处理：一键读取、发票列表、监控预览、回收站删除与同号检查。" },
  { key: "bank_flow_dir", label: "银行流水", short_tag: "流水", description: "按银行流水处理：支持属期文件夹核对、确认移动与银行版式识别映射。" },
  { key: "input_deduction_dir", label: "进项抵扣", short_tag: "抵扣", description: "按进项抵扣勾选清单处理：支持属期文件夹核对与确认移动。" },
  { key: "payroll_social_dir", label: "工资社保", short_tag: "工资", description: "按工资社保资料处理：支持只读读取本目录社保应缴明细文件。" },
  { key: "general", label: "普通资料（未指定）", short_tag: "资料", description: "通用文件夹：支持查看发票、读取数据、设为监控目录与预览/回收站删除，可随时调整指向。" },
];

const props = defineProps<{ company: Company; subdir: CompanySubdir }>();
const emit = defineEmits<{ close: []; done: [nextKey?: string] }>();

const companies = useCompaniesStore();
const isCustom = computed(() => props.subdir.kind === "custom");
const isExternal = computed(() => props.subdir.location === "external");
const isMonitored = computed(() => props.company.monitored && props.company.monitored_subdir_key === props.subdir.key);
const roles = computed<FolderRoleMeta[]>(() => companies.list?.folder_roles ?? DEFAULT_ROLES);

const label = ref(props.subdir.label);
const role = ref<FolderRole>((props.subdir.role ?? (props.subdir.key as FolderRole)) || "general");
const renameDisk = ref(false);
const diskTarget = ref(
  props.subdir.location === "external"
    ? props.subdir.path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? ""
    : props.subdir.relative_path,
);
const diskTargetTouched = ref(false);
const busy = ref(false);
const promoting = ref(false);
const confirmPromote = ref(false);
const error = ref("");

const roleDesc = computed(() => roles.value.find((item) => item.key === role.value)?.description ?? "");
const canPromote = computed(() => isCustom.value && !isExternal.value && role.value !== "general");
const roleLabel = computed(() => roles.value.find((item) => item.key === role.value)?.label ?? role.value);

function syncDiskTargetFromLabel(raw: string): void {
  const trimmed = raw.trim();
  if (isExternal.value) {
    diskTarget.value = trimmed;
  } else {
    const parts = props.subdir.relative_path.split("/");
    parts[parts.length - 1] = trimmed;
    diskTarget.value = parts.join("/");
  }
}

watch(label, (val) => {
  if (renameDisk.value && !diskTargetTouched.value) syncDiskTargetFromLabel(val);
});
watch(renameDisk, (checked) => {
  if (checked && !diskTargetTouched.value && label.value.trim()) syncDiskTargetFromLabel(label.value);
});

async function save(): Promise<void> {
  if (!label.value.trim()) {
    error.value = "文件夹名称不能为空。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const payload: {
      label?: string;
      role?: FolderRole;
      rename_disk?: boolean;
      new_relative_path?: string;
      new_name?: string;
    } = { label: label.value.trim() };
    if (isCustom.value) payload.role = role.value;
    if (renameDisk.value) {
      payload.rename_disk = true;
      if (isExternal.value) payload.new_name = diskTarget.value.trim();
      else payload.new_relative_path = diskTarget.value.trim();
    }
    await companies.updateFolder(props.company.id, props.subdir.key, payload);
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    toast(renameDisk.value ? `已重命名文件夹「${label.value.trim()}」` : `已保存「${label.value.trim()}」设置`, "info", 3000);
    emit("done", props.subdir.key);
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

async function promote(): Promise<void> {
  if (!canPromote.value || promoting.value) return;
  promoting.value = true;
  error.value = "";
  try {
    const result = await companies.promoteFolder(props.company.id, props.subdir.key, {
      target_role: role.value,
      keep_previous_as_custom: true,
    });
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    toast(`已将「${props.subdir.label}」切换为该公司主「${roleLabel.value}」目录`, "info", 3600);
    emit("done", result.promoted_to);
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    promoting.value = false;
    confirmPromote.value = false;
  }
}
</script>

<template>
  <WsModal
    :title="`重命名与功能指向 · ${subdir.label}`"
    :subtitle="`${company.name} · ${isCustom ? (isExternal ? '外部导入文件夹' : '公司内自定义文件夹') : '默认标准文件夹'}`"
    @close="!busy && !promoting && emit('close')"
  >
    <form class="folder-edit-body" @submit.prevent="save">
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <label class="field">
        <span>显示名称</span>
        <input v-model="label" maxlength="80" required autocomplete="off" :disabled="busy || promoting">
      </label>

      <label v-if="isCustom" class="field">
        <span>功能指向（以默认 6 类目录为基准）</span>
        <select v-model="role" :disabled="busy || promoting">
          <option v-for="item in roles" :key="item.key" :value="item.key">{{ item.label }}</option>
        </select>
        <small class="muted">{{ roleDesc }}</small>
      </label>
      <p v-else class="overview-notice">
        <span>默认槽位功能指向固定为「<strong>{{ subdir.role_label || subdir.default_label || subdir.label }}</strong>」，参与公司账簿、成本分析与凭证草稿。</span>
      </p>

      <div class="panel folder-disk-box">
        <label class="folder-check-row">
          <input v-model="renameDisk" type="checkbox" :disabled="busy || promoting || isMonitored || subdir.status !== 'present'">
          <span>同时重命名硬盘上的实际文件夹</span>
        </label>
        <p v-if="isMonitored" class="muted">当前正在监控此文件夹，如需重命名硬盘文件夹请先切换监控目录（可只修改上方显示名称）。</p>
        <p v-else-if="subdir.status !== 'present'" class="muted">硬盘上该文件夹目前缺失或不可用，仅可修改显示名称。</p>
        <label v-if="renameDisk" class="field">
          <span>{{ isExternal ? "新文件夹名（同一上级目录内）" : "新的公司内相对路径" }}</span>
          <input v-model="diskTarget" class="mono" required autocomplete="off" :disabled="busy || promoting" @input="diskTargetTouched = true">
        </label>
        <p class="muted path mono">当前路径：{{ subdir.path }}</p>
      </div>

      <div class="actions">
        <button type="submit" class="primary" :disabled="busy || promoting" :aria-busy="busy">{{ busy ? "保存中…" : "保存修改" }}</button>
        <button type="button" class="ghost" :disabled="busy || promoting" @click="emit('close')">取消</button>
      </div>
    </form>

    <section v-if="canPromote" class="folder-promote-box">
      <hr>
      <h4>切换为主标准目录</h4>
      <p class="muted">
        当前自定义文件夹位于公司资料夹内，且功能指向「{{ roleLabel }}」。可一键将其设为该公司的主「{{ roleLabel }}」目录（参与公司账簿/成本/做账）；原有主目录若存在会自动保留为自定义文件夹，绝不移动或删除文件。
      </p>
      <div v-if="!confirmPromote" class="actions">
        <button type="button" :disabled="busy || promoting" @click="confirmPromote = true">设为主「{{ roleLabel }}」目录…</button>
      </div>
      <div v-else class="actions" role="alertdialog" aria-label="确认切换主目录">
        <span>确认将「{{ subdir.relative_path }}」切换为主「{{ roleLabel }}」目录？</span>
        <button type="button" class="primary" :disabled="promoting" :aria-busy="promoting" @click="promote">{{ promoting ? "切换中…" : "确认切换" }}</button>
        <button type="button" class="ghost" :disabled="promoting" @click="confirmPromote = false">取消</button>
      </div>
    </section>
  </WsModal>
</template>

<style scoped>
.folder-edit-body { display: grid; gap: 12px; }
.folder-disk-box { padding: 12px; display: grid; gap: 8px; font-size: 13px; }
.folder-disk-box p { margin: 0; }
.folder-check-row { display: flex; align-items: center; gap: 8px; font-weight: 600; cursor: pointer; }
.folder-promote-box { margin-top: 14px; display: grid; gap: 8px; }
.folder-promote-box h4, .folder-promote-box p { margin: 0; font-size: 13px; }
</style>
