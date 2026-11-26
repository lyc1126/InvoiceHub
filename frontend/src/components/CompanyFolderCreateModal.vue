<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ApiError } from "../api/client";
import type {
  Company,
  CompanyFolderCreatePlan,
  CompanyFolderDiscoverPayload,
  DiscoveredFolderCandidate,
  FolderRole,
  FolderRoleMeta,
} from "../api/types";
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

const props = withDefaults(defineProps<{ company: Company; initialMode?: "create" | "import" | "restore" }>(), {
  initialMode: "create",
});
const emit = defineEmits<{ close: []; done: [folderId?: string] }>();

const companies = useCompaniesStore();
const mode = ref<"create" | "import" | "restore">(props.initialMode);
const loading = ref(false);
const busy = ref(false);
const picking = ref(false);
const error = ref("");
const discovered = ref<CompanyFolderDiscoverPayload | null>(null);

// Create form state
const createLabel = ref("");
const createRelPath = ref("");
const createRelTouched = ref(false);
const createRole = ref<FolderRole>("cost_invoice_dir");
const createPlan = ref<CompanyFolderCreatePlan | null>(null);

// Import form state
const importPath = ref("");
const importLabel = ref("");
const importLabelTouched = ref(false);
const importRole = ref<FolderRole>("cost_invoice_dir");

let generation = 0;
let pickGeneration = 0;

const roles = computed<FolderRoleMeta[]>(() => discovered.value?.roles?.length ? discovered.value.roles : (companies.list?.folder_roles ?? DEFAULT_ROLES));
const createRoleDesc = computed(() => roles.value.find((r) => r.key === createRole.value)?.description ?? "");
const importRoleDesc = computed(() => roles.value.find((r) => r.key === importRole.value)?.description ?? "");
const hiddenDefaults = computed(() => discovered.value?.hidden_standard_subdirs ?? []);

watch(createLabel, (val) => {
  if (!createRelTouched.value) createRelPath.value = val.trim();
  createPlan.value = null;
});
watch([createRelPath, createRole], () => { createPlan.value = null; });

function onImportPathInput(): void {
  if (!importLabelTouched.value) {
    const cleaned = importPath.value.trim().replace(/[\\/]+$/, "");
    const parts = cleaned.split(/[\\/]/).filter(Boolean);
    importLabel.value = parts[parts.length - 1] ?? "";
  }
}

async function loadDiscover(): Promise<void> {
  const mine = ++generation;
  loading.value = true;
  error.value = "";
  try {
    const next = await companies.discoverFolders(props.company.id);
    if (mine === generation) {
      discovered.value = next;
      if (mode.value === "restore" && !next.hidden_standard_subdirs.length) mode.value = "create";
    }
  } catch (cause) {
    if (mine === generation) error.value = errorText(cause);
  } finally {
    if (mine === generation) loading.value = false;
  }
}

function chooseCandidate(item: DiscoveredFolderCandidate): void {
  importPath.value = item.path;
  importLabel.value = item.label;
  importLabelTouched.value = false;
  importRole.value = item.suggested_role;
  error.value = "";
}

async function pickDirectory(): Promise<void> {
  if (picking.value || busy.value) return;
  const mine = ++pickGeneration;
  picking.value = true;
  error.value = "";
  try {
    const result = await companies.pickFolderDirectory();
    if (mine !== pickGeneration) return;
    if (result.selected && result.path) {
      importPath.value = result.path;
      importLabelTouched.value = false;
      onImportPathInput();
    }
  } catch (cause) {
    if (mine === pickGeneration) error.value = errorText(cause);
  } finally {
    if (mine === pickGeneration) picking.value = false;
  }
}

async function previewCreate(): Promise<void> {
  if (!createLabel.value.trim()) {
    error.value = "请填写文件夹名称。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    createPlan.value = await companies.previewCreateFolder(props.company.id, {
      label: createLabel.value.trim(),
      relative_path: createRelPath.value.trim() || createLabel.value.trim(),
      role: createRole.value,
    });
  } catch (cause) {
    error.value = errorText(cause);
    createPlan.value = null;
  } finally {
    busy.value = false;
  }
}

async function confirmCreate(): Promise<void> {
  if (!createPlan.value || createPlan.value.action !== "create" || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await companies.createFolder(props.company.id, {
      label: createPlan.value.label,
      relative_path: createPlan.value.relative_path,
      role: createPlan.value.role,
      plan_hash: createPlan.value.plan_hash,
    });
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    toast(`已新建文件夹「${createPlan.value.label}」`, "info", 3000);
    emit("done", result.folder_id);
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.code === "COMPANY_PLAN_STALE"
      ? "目录状态已变化，请重新预览后确认。"
      : errorText(cause);
    createPlan.value = null;
  } finally {
    busy.value = false;
  }
}

async function confirmImport(): Promise<void> {
  if (!importPath.value.trim()) {
    error.value = "请选择或填写要导入的文件夹路径。";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const result = await companies.importFolder(props.company.id, {
      path: importPath.value.trim(),
      label: importLabel.value.trim() || undefined,
      role: importRole.value,
    });
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    toast(`已导入文件夹「${importLabel.value.trim() || importPath.value.trim()}」`, "info", 3000);
    emit("done", result.folder_id);
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

async function restoreDefault(key: string, label: string): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await companies.restoreFolder(props.company.id, key);
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
    toast(`已恢复显示默认文件夹「${label}」`, "info", 2800);
    await loadDiscover();
    if (!hiddenDefaults.value.length) emit("done", key);
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

onMounted(() => void loadDiscover());
onBeforeUnmount(() => { ++generation; ++pickGeneration; });
</script>

<template>
  <WsModal
    :title="`管理文件夹 · ${company.name}`"
    subtitle="新建空文件夹或导入已存在的文件夹，并指定以默认目录为基准的功能指向。"
    @close="!busy && !picking && emit('close')"
  >
    <div class="tabs folder-modal-tabs" role="tablist" aria-label="文件夹操作类型">
      <button type="button" role="tab" :aria-selected="mode === 'create'" @click="mode = 'create'; error = ''">新建空文件夹</button>
      <button type="button" role="tab" :aria-selected="mode === 'import'" @click="mode = 'import'; error = ''">导入已有文件夹</button>
      <button v-if="hiddenDefaults.length" type="button" role="tab" :aria-selected="mode === 'restore'" @click="mode = 'restore'; error = ''">
        恢复隐藏默认目录（{{ hiddenDefaults.length }}）
      </button>
    </div>

    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

    <div v-if="mode === 'create'" class="folder-modal-body">
      <p class="overview-notice"><span>在公司资料夹内新建空文件夹，不移动或改写任何已有文件。自定义文件夹默认独立查看，不自动并入公司总账/成本 V2。</span></p>
      <label class="field">
        <span>文件夹显示名称</span>
        <input v-model="createLabel" maxlength="80" placeholder="例如：临时验收副本、2026补充成本" autocomplete="off" :disabled="busy">
      </label>
      <label class="field">
        <span>公司资料夹内相对路径</span>
        <input v-model="createRelPath" class="mono" placeholder="默认与显示名称相同，也可填子路径如 补充/成本" autocomplete="off" :disabled="busy" @input="createRelTouched = true">
      </label>
      <label class="field">
        <span>功能指向（以默认 6 类目录为基准）</span>
        <select v-model="createRole" :disabled="busy">
          <option v-for="item in roles" :key="item.key" :value="item.key">{{ item.label }}</option>
        </select>
        <small class="muted">{{ createRoleDesc }}</small>
      </label>

      <div v-if="createPlan" class="panel folder-plan-box" aria-label="新建预览">
        <p><strong>创建路径：</strong><span class="path mono">{{ createPlan.path }}</span></p>
        <p><strong>功能指向：</strong><span class="tag">{{ createPlan.role_label }}</span></p>
        <p v-if="createPlan.action === 'blocked'" class="banner banner--error" role="alert">{{ createPlan.reason }}</p>
        <p v-else class="muted">确认后将在上述位置新建一个空文件夹并加入侧栏列表。</p>
      </div>

      <div class="actions">
        <button v-if="!createPlan || createPlan.action !== 'create'" type="button" class="primary" :disabled="busy || !createLabel.trim()" :aria-busy="busy" @click="previewCreate">
          {{ busy ? "预览中…" : "预览创建" }}
        </button>
        <button v-else type="button" class="primary" :disabled="busy" :aria-busy="busy" @click="confirmCreate">
          {{ busy ? "创建中…" : "确认创建空文件夹" }}
        </button>
        <button type="button" class="ghost" :disabled="busy" @click="emit('close')">取消</button>
      </div>
    </div>

    <div v-else-if="mode === 'import'" class="folder-modal-body">
      <p class="overview-notice"><span>可导入公司资料夹内已有文件夹，也可跨路径导入本机其它位置的文件夹。导入只记录路径与功能指向，绝不移动、修改或删除原文件。</span></p>

      <div v-if="loading" class="muted" role="status" aria-busy="true">正在扫描公司资料夹内未登记的文件夹…</div>
      <div v-else-if="discovered?.candidates.length" class="folder-candidates">
        <p class="muted">公司资料夹内发现以下未登记文件夹（点击一键填入）：</p>
        <div class="folder-candidate-chips">
          <button
            v-for="item in discovered.candidates"
            :key="item.relative_path"
            type="button"
            class="folder-chip"
            :class="{ 'folder-chip--active': importPath === item.path }"
            @click="chooseCandidate(item)"
          >
            <span>{{ item.relative_path }}</span>
            <small class="muted">{{ item.suggested_role_label }}</small>
          </button>
        </div>
      </div>

      <label class="field">
        <span>要导入的文件夹路径（公司内或电脑上任意本地文件夹）</span>
        <div class="field-row">
          <input v-model="importPath" class="mono" placeholder="点击右侧选择文件夹，或粘贴本机路径" autocomplete="off" :disabled="busy || picking" @input="onImportPathInput">
          <button type="button" :disabled="busy || picking" :aria-busy="picking" @click="pickDirectory">{{ picking ? "选择中…" : "选择文件夹…" }}</button>
        </div>
      </label>
      <label class="field">
        <span>显示名称</span>
        <input v-model="importLabel" maxlength="80" placeholder="留空则使用原文件夹名" autocomplete="off" :disabled="busy" @input="importLabelTouched = true">
      </label>
      <label class="field">
        <span>功能指向（以默认 6 类目录为基准）</span>
        <select v-model="importRole" :disabled="busy">
          <option v-for="item in roles" :key="item.key" :value="item.key">{{ item.label }}</option>
        </select>
        <small class="muted">{{ importRoleDesc }}</small>
      </label>

      <div class="actions">
        <button type="button" class="primary" :disabled="busy || picking || !importPath.trim()" :aria-busy="busy" @click="confirmImport">
          {{ busy ? "导入中…" : "确认导入" }}
        </button>
        <button type="button" class="ghost" :disabled="busy || picking" @click="emit('close')">取消</button>
      </div>
    </div>

    <div v-else class="folder-modal-body">
      <p class="overview-notice"><span>以下默认文件夹此前已从侧栏隐藏（硬盘上的原文件未改动），点击即可恢复显示。</span></p>
      <table class="grid">
        <thead><tr><th>默认类型</th><th>路径</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in hiddenDefaults" :key="item.key">
            <td>{{ item.label }}</td>
            <td class="path mono">{{ item.relative_path }}</td>
            <td><button type="button" :disabled="busy" @click="restoreDefault(item.key, item.label)">恢复显示</button></td>
          </tr>
        </tbody>
      </table>
      <div class="actions">
        <button type="button" class="ghost" :disabled="busy" @click="emit('close')">关闭</button>
      </div>
    </div>
  </WsModal>
</template>

<style scoped>
.folder-modal-tabs { margin-bottom: 10px; }
.folder-modal-body { display: grid; gap: 10px; }
.folder-plan-box { padding: 10px 12px; display: grid; gap: 5px; font-size: 13px; }
.folder-plan-box p { margin: 0; }
.folder-candidates { display: grid; gap: 6px; }
.folder-candidates p { margin: 0; font-size: 13px; }
.folder-candidate-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.folder-chip { display: inline-flex; align-items: center; gap: 6px; height: auto; min-height: 30px; padding: 4px 10px; font-size: 13px; }
.folder-chip--active { background: var(--ws-selected); border-color: var(--ws-active-line); font-weight: 600; }
</style>
