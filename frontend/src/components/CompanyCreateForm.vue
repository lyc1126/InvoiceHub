<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { request } from "../api/client";
import type { CompanyDetection, CompanyPayload, CompanySetupJob, TaxpayerType } from "../api/types";
import { errorText, SUBDIR_STATUS_LABELS } from "../format";
import { useCompaniesStore } from "../stores/companies";
import MonthPicker from "./MonthPicker.vue";

const emit = defineEmits<{ created: [sources: Record<string, string>]; cancel: [] }>();
const companies = useCompaniesStore();
const mode = ref<"existing" | "new">("existing");
// Prototype wizard: taxpayer identity is an explicit choice (no system default). "稍后设置"
// keeps the existing unset state; the radio is required so nothing is assumed silently.
const taxpayerChoice = ref<"" | "general" | "small_scale" | "later">("");
watch(taxpayerChoice, (value) => { form.taxpayer_type = value === "general" || value === "small_scale" ? value : ""; });
const form = reactive({ name: "", root_dir: "", parent_dir: "", folder_name: "", taxpayer_type: "" as TaxpayerType | "", effective_from: "" });
const subdirs = reactive<Record<string, string>>({});
const standards = computed(() => companies.list?.standard_subdirs ?? []);
const busy = ref(false);
const picking = ref(false);
const error = ref("");
const notice = ref("");
const plan = ref<CompanySetupJob | null>(null);
const submitted = ref(false);
const detection = ref<CompanyDetection | null>(null);
const detecting = ref(false);
const createMissing = ref<string[]>([]);
const registrationHash = ref("");
const existingSubdirs = reactive<Record<string, string>>({});
const chosenSubdirs = () => Object.fromEntries(Object.entries(existingSubdirs).filter(([, value]) => value));
const needsSelection = computed(() => detection.value?.subdirs.some(item => item.selection_required) ?? false);
let detectGeneration = 0;
let detectTimer: ReturnType<typeof setTimeout> | undefined;
watch(() => `${mode.value}:${form.root_dir}`, () => {
  for (const key of Object.keys(existingSubdirs)) delete existingSubdirs[key];
  detect();
});
// Also run by "重新检测": a stale plan (409) or failed registration leaves the same path, so
// the watch alone could not produce the fresh plan_hash the next registration needs.
function detect(delay = 300): void {
  detection.value = null;
  createMissing.value = [];
  error.value = "";
  const mine = ++detectGeneration;
  clearTimeout(detectTimer);
  detecting.value = false;
  if (mode.value !== "existing" || !form.root_dir.trim()) return;
  detecting.value = true;
  detectTimer = setTimeout(async () => {
    try {
      const result = await request<CompanyDetection>("/api/v1/companies/detect", { method: "POST", body: { root_dir: form.root_dir, subdirs: chosenSubdirs() } });
      if (!disposed && mine === detectGeneration) {
        detection.value = result;
        for (const item of result.subdirs) existingSubdirs[item.key] = item.selection_required ? "" : item.relative_path;
      }
    } catch (cause) {
      if (!disposed && mine === detectGeneration) error.value = errorText(cause);
    } finally {
      if (mine === detectGeneration) detecting.value = false;
    }
  }, delay);
}
async function readRegistration(): Promise<void> {
  if (busy.value || !registrationHash.value) return;
  busy.value = true;
  try {
    const result = await request<CompanyPayload & { state: string; message: string }>(`/api/v1/companies/registration-jobs/${registrationHash.value}`);
    if (disposed) return;
    if (result.state === "completed") {
      if (result.company) companies.selectedId = result.company.id;
      await companies.load();
      emit("created", result.subdir_sources ?? {});
    } else if (result.state === "failed") {
      // The server records "failed" only before the registry write; re-detect, then the
      // user confirms again. Directories already created stay and show up as found.
      registrationHash.value = "";
      detect(0);
      error.value = `${result.message || "登记未完成。"} 已重新检测，请核对后再登记。`;
    } else error.value = result.message || "登记结果待核对；不会重复提交。";
  } catch (cause) { if (!disposed) error.value = `登记结果待核对：${errorText(cause)}`; }
  finally { busy.value = false; }
}
let disposed = false;
let pickerGeneration = 0;
let pickerController: AbortController | undefined;
const planInput = () => ({ name: form.name, parent_dir: form.parent_dir, folder_name: form.folder_name,
  subdirs: { ...subdirs }, taxpayer_periods: form.taxpayer_type ? [{ effective_from: form.effective_from, taxpayer_type: form.taxpayer_type }] : [] });

watch(() => standards.value.map((item) => `${item.key}:${item.label}`).join("/"), () => {
  for (const item of standards.value) if (!(item.key in subdirs)) subdirs[item.key] = item.label;
}, { immediate: true });
watch(() => form.name, (value, previous) => {
  if (!form.folder_name || form.folder_name === previous) form.folder_name = value;
});

async function pick(): Promise<void> {
  if (picking.value || busy.value) return;
  const mine = ++pickerGeneration;
  const field = mode.value === "new" ? "parent_dir" : "root_dir";
  const before = form[field];
  const originalMode = mode.value;
  pickerController = new AbortController();
  picking.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await request<{ selected: boolean; path: string }>("/api/v1/companies/pick-directory", {
      method: "POST", body: {}, timeoutMs: 130_000, signal: pickerController.signal,
    });
    if (disposed || mine !== pickerGeneration) return;
    // A native dialog is asynchronous. A manually edited draft or changed mode wins over
    // its late return; selection never registers a company or changes the monitored folder.
    if (mode.value !== originalMode || form[field] !== before) {
      notice.value = "路径草稿已修改，未采用选择器的迟到结果。";
    } else if (result.selected) {
      form[field] = result.path;
      notice.value = "已选择，尚未登记或创建。";
    } else notice.value = "已取消选择，原路径草稿保留。";
  } catch (cause) {
    if (!disposed && mine === pickerGeneration) error.value = errorText(cause);
  } finally {
    if (mine === pickerGeneration) picking.value = false;
  }
}

async function submit(): Promise<void> {
  if (busy.value || picking.value || plan.value || registrationHash.value || !taxpayerChoice.value) return;
  if (mode.value === "existing" && (!detection.value || detection.value.root_status !== "present" || needsSelection.value)) return;
  error.value = "";
  notice.value = "";
  if (form.taxpayer_type && !form.effective_from) {
    error.value = "请填写纳税人身份的生效月份。";
    return;
  }
  busy.value = true;
  try {
    if (mode.value === "existing") {
      registrationHash.value = detection.value!.plan_hash;
      const result = await companies.create({ name: form.name, root_dir: form.root_dir,
        create_missing: [...createMissing.value], plan_hash: registrationHash.value,
        subdirs: chosenSubdirs(),
        // Empty stays 未设置; no taxpayer type is assumed.
        taxpayer_periods: form.taxpayer_type ? [{ effective_from: form.effective_from, taxpayer_type: form.taxpayer_type }] : [] });
      if (!disposed && result.company) emit("created", result.subdir_sources ?? {});
      else if (!disposed) error.value = "登记结果待核对，请读取执行结果。";
    } else {
      const input = planInput();
      const result = await companies.planSetup(input);
      if (disposed) return;
      if (JSON.stringify(input) !== JSON.stringify(planInput())) {
        notice.value = "资料已修改，请按当前内容重新预览。";
        return;
      }
      plan.value = result;
      submitted.value = false;
    }
  } catch (cause) {
    if (!disposed) {
      error.value = errorText(cause);
      // Definitive validation conflicts have no side effects; an unknown response stays query-only.
      if (cause instanceof Error && "status" in cause && Number(cause.status) >= 400 && Number(cause.status) < 500) {
        registrationHash.value = "";
        detection.value = null;
        error.value += "；请点“重新检测”后再登记。";
      }
    }
  } finally {
    busy.value = false;
  }
}

async function confirm(): Promise<void> {
  if (!plan.value || busy.value) return;
  const current = plan.value;
  busy.value = true;
  error.value = "";
  try {
    let result: CompanySetupJob;
    if (submitted.value) result = await companies.getSetup(current.job_id);
    else {
      submitted.value = true;
      try {
        result = await companies.confirmSetup(current);
      } catch (cause) {
        // Once confirmation was sent, only GET the durable result. A timeout cannot
        // authorize replaying mkdir or registration, even after a component remount.
        result = await companies.getSetup(current.job_id);
        if (result.state === "prepared") throw cause;
      }
    }
    if (disposed) return;
    plan.value = result;
    if (result.state === "completed") {
      await companies.acceptSetup(result);
      if (!disposed) emit("created", Object.fromEntries(result.items.map((item) => [item.key, "created"])));
    }
  } catch (cause) {
    if (!disposed) error.value = `未能确认创建结果：${errorText(cause)}。请读取执行结果，不会重复创建。`;
  } finally {
    busy.value = false;
  }
}

function changeMode(next: "existing" | "new"): void {
  if (busy.value || picking.value || submitted.value) return;
  mode.value = next;
  plan.value = null;
  error.value = "";
  notice.value = "";
}

onBeforeUnmount(() => {
  disposed = true;
  pickerGeneration += 1;
  pickerController?.abort();
  clearTimeout(detectTimer);
  detectGeneration += 1;
});
</script>

<template>
  <form class="company-create wz-form" aria-label="新建公司" @submit.prevent="submit">
    <span class="period-segment" role="group" aria-label="资料夹来源">
      <button type="button" :aria-pressed="mode === 'existing'" :disabled="busy || picking || submitted" @click="changeMode('existing')">登记已有资料夹</button>
      <button type="button" :aria-pressed="mode === 'new'" :disabled="busy || picking || submitted" @click="changeMode('new')">新建工作区</button>
    </span>
    <template v-if="!plan">
      <label v-if="mode === 'existing'" class="field">
        <span>公司资料夹（可以是空文件夹）</span>
        <span class="wz-row">
          <input v-model="form.root_dir" aria-label="公司资料夹" required placeholder="选择或粘贴已存在的文件夹路径" autocomplete="off" :disabled="busy || !!registrationHash">
          <button type="button" :disabled="busy || picking || !!registrationHash" :aria-busy="picking" @click="pick">{{ picking ? '正在选择…' : '选择公司资料夹…' }}</button>
        </span>
        <small class="muted">成本发票、开具发票等子目录会按名称自动识别；勾选后，登记时仅补建所选空目录。</small>
      </label>
      <template v-else>
        <label class="field">
          <span>上级文件夹</span>
          <span class="wz-row">
            <input v-model="form.parent_dir" aria-label="上级文件夹" required autocomplete="off" :disabled="busy || !!registrationHash">
            <button type="button" :disabled="busy || picking || !!registrationHash" :aria-busy="picking" @click="pick">{{ picking ? '正在选择…' : '选择上级文件夹…' }}</button>
          </span>
          <small class="muted">先选择上级位置并填写名称，核对计划后再创建空目录。现有文件不会移动、改名或覆盖。</small>
        </label>
      </template>
      <section v-if="mode === 'existing'" aria-label="检测结果">
        <p v-if="!detecting && !detection && form.root_dir.trim()"><button type="button" :disabled="busy || picking || !!registrationHash" @click="detect(0)">重新检测</button></p>
        <p v-if="detecting" class="muted" aria-busy="true">正在检测资料夹…</p>
        <template v-else-if="detection">
          <p v-if="detection.root_status !== 'present'" class="banner banner--error">资料夹不可用：{{ SUBDIR_STATUS_LABELS[detection.root_status] }}</p>
          <div class="overview-table-wrap"><table class="grid">
            <thead><tr><th>子目录</th><th>检测</th><th>处理</th></tr></thead>
            <tbody><tr v-for="item in detection.subdirs" :key="item.key">
              <td>{{ item.label }}
                <select v-if="(item.candidates?.length ?? 0) > 1" v-model="existingSubdirs[item.key]" class="wz-candidate" :aria-label="`${item.label} 候选目录`" :disabled="busy || detecting || !!registrationHash" @change="detect(0)">
                  <option v-if="item.selection_required" value="">多个候选，请选择</option>
                  <option v-for="candidate in item.candidates" :key="candidate" :value="candidate">{{ candidate }}</option>
                  <option v-if="!item.candidates?.includes(item.label)" :value="item.label">使用标准目录 {{ item.label }}（可另行补建）</option>
                </select>
                <small v-else-if="item.relative_path !== item.label" class="mono"> · {{ item.relative_path }}</small>
              </td>
              <td>{{ item.status === 'present' ? `找到 · ${item.file_count === null ? '文件数待核对' : item.file_count + ' 个文件'}` : SUBDIR_STATUS_LABELS[item.status] }}</td>
              <td><span v-if="item.selection_required">请先选择，不自动猜测</span><label v-else-if="item.suggested_action === 'create'"><input v-model="createMissing" type="checkbox" :value="item.key" :disabled="busy || !!registrationHash">创建空文件夹</label><span v-else>保留原状</span></td>
            </tr></tbody>
          </table></div>
          <p v-if="createMissing.length" class="overview-notice">点击“登记”即确认创建勾选的 {{ createMissing.length }} 类空目录；不会移动、改名或覆盖文件。</p>
        </template>
      </section>
      <label class="field"><span>公司名称</span><input v-model="form.name" aria-label="公司名称" required maxlength="80" autocomplete="off" :disabled="busy || !!registrationHash"></label>
      <label v-if="mode === 'new'" class="field"><span>新公司文件夹名称</span><input v-model="form.folder_name" aria-label="新公司文件夹名称" required maxlength="80" autocomplete="off" :disabled="busy || !!registrationHash"></label>
      <fieldset class="field">
        <legend>纳税人身份（必选，系统不默认）</legend>
        <span class="radio-row">
          <label><input v-model="taxpayerChoice" type="radio" name="taxpayer" value="general" required :disabled="busy || !!registrationHash">一般纳税人</label>
          <label><input v-model="taxpayerChoice" type="radio" name="taxpayer" value="small_scale" :disabled="busy || !!registrationHash">小规模纳税人</label>
          <label><input v-model="taxpayerChoice" type="radio" name="taxpayer" value="later" :disabled="busy || !!registrationHash">稍后设置</label>
          <MonthPicker v-if="form.taxpayer_type" v-model="form.effective_from" label="生效月份" placeholder="选择生效年月" :disabled="busy || !!registrationHash" />
        </span>
      </fieldset>
      <fieldset v-if="mode === 'new'" class="field">
        <legend>六类资料目录（可调整）</legend>
        <div class="overview-table-wrap"><table class="grid">
          <thead><tr><th>资料类型</th><th>子目录名称</th></tr></thead>
          <tbody><tr v-for="item in standards" :key="item.key"><td>{{ item.label }}</td><td><input v-model="subdirs[item.key]" :aria-label="`${item.label} 子目录`" required :disabled="busy || !!registrationHash" autocomplete="off"></td></tr></tbody>
        </table></div>
      </fieldset>
    </template>
    <section v-else class="wz-plan" aria-label="新建工作区计划">
      <p class="overview-notice"><span><b>{{ plan.state === 'prepared' ? '核对创建计划' : '创建结果' }}</b> · {{ plan.name }}</span></p>
      <p class="path mono">{{ plan.root_path }}</p>
      <div class="overview-table-wrap"><table class="grid">
        <thead><tr><th>资料类型</th><th>将创建</th></tr></thead>
        <tbody><tr v-for="item in plan.items" :key="item.key"><td>{{ item.label }}</td><td class="mono">{{ item.relative_path }}</td></tr></tbody>
      </table></div>
      <p v-if="plan.state === 'prepared'" class="muted">确认后创建上述公司文件夹与六类空目录并登记；监控目录保持原样。</p>
      <p v-else role="status">{{ plan.message }}</p>
      <p v-if="plan.created.length" class="muted">已创建：{{ plan.created.join('、') }}</p>
      <p v-if="plan.state === 'unknown' || plan.state === 'failed'" class="muted">创建任务 {{ plan.job_id }}；已创建的目录保留，不会自动重试或删除。</p>
      <div class="actions">
        <button type="button" class="primary" :disabled="busy || plan.state === 'completed' || plan.state === 'failed'" :aria-busy="busy" @click="confirm">{{ submitted ? '读取执行结果' : '确认创建并登记' }}</button>
        <button v-if="!submitted" type="button" class="ghost" :disabled="busy || !!registrationHash" @click="plan = null">返回修改</button>
      </div>
    </section>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="banner banner--note" role="status">{{ notice }}</p>
    <div v-if="!plan || submitted" class="actions">
      <button v-if="!plan" type="submit" class="primary" :disabled="busy || picking || !taxpayerChoice || !!registrationHash || (mode === 'existing' && (detecting || !detection || detection.root_status !== 'present' || needsSelection))" :aria-busy="busy">{{ busy ? '处理中…' : mode === 'existing' ? '登记' : '预览创建计划' }}</button>
      <button v-if="registrationHash" type="button" :disabled="busy" @click="readRegistration">读取登记结果</button>
      <button type="button" class="ghost" :disabled="busy" @click="emit('cancel')">{{ submitted ? '关闭' : '取消' }}</button>
      <span v-if="!plan && !taxpayerChoice" class="muted">先选纳税人身份</span>
    </div>
  </form>
</template>

<style scoped>
.wz-candidate { display: block; max-width: 240px; margin-top: 4px; }
</style>
