<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { request } from "../api/client";
import type { CompanySetupJob, TaxpayerType } from "../api/types";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";

const emit = defineEmits<{ created: [sources: Record<string, string>]; cancel: [] }>();
const companies = useCompaniesStore();
const mode = ref<"existing" | "new">("existing");
const form = reactive({ name: "", root_dir: "", parent_dir: "", folder_name: "", taxpayer_type: "" as TaxpayerType | "", effective_from: "" });
const subdirs = reactive<Record<string, string>>({});
const standards = computed(() => companies.list?.standard_subdirs ?? []);
const busy = ref(false);
const picking = ref(false);
const error = ref("");
const notice = ref("");
const plan = ref<CompanySetupJob | null>(null);
const submitted = ref(false);
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
  if (busy.value || picking.value || plan.value) return;
  error.value = "";
  notice.value = "";
  if (form.taxpayer_type && !form.effective_from) {
    error.value = "请填写纳税人身份的生效月份。";
    return;
  }
  busy.value = true;
  try {
    if (mode.value === "existing") {
      const result = await companies.create({ name: form.name, root_dir: form.root_dir,
        // Empty stays 未设置; no taxpayer type is assumed.
        taxpayer_periods: form.taxpayer_type ? [{ effective_from: form.effective_from, taxpayer_type: form.taxpayer_type }] : [] });
      if (!disposed) emit("created", result.subdir_sources ?? {});
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
    if (!disposed) error.value = errorText(cause);
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
});
</script>

<template>
  <form class="panel company-create" aria-label="新建公司" @submit.prevent="submit">
    <h2>添加公司资料夹</h2>
    <div class="actions" role="group" aria-label="资料夹来源">
      <button type="button" :class="{ primary: mode === 'existing' }" :aria-pressed="mode === 'existing'" :disabled="busy || picking || submitted" @click="changeMode('existing')">登记已有资料夹</button>
      <button type="button" :class="{ primary: mode === 'new' }" :aria-pressed="mode === 'new'" :disabled="busy || picking || submitted" @click="changeMode('new')">新建工作区</button>
    </div>
    <template v-if="!plan">
      <label class="field">
        <span>公司名称</span>
        <input v-model="form.name" aria-label="公司名称" required maxlength="80" autocomplete="off" :disabled="busy">
      </label>
      <label v-if="mode === 'existing'" class="field">
        <span>公司资料夹（待登记）</span>
        <input v-model="form.root_dir" aria-label="公司资料夹" required placeholder="选择或粘贴已存在的文件夹路径" autocomplete="off" :disabled="busy">
        <button type="button" :disabled="busy || picking" :aria-busy="picking" @click="pick">{{ picking ? '正在选择…' : '选择公司资料夹…' }}</button>
        <small class="muted">成本发票、开具发票等子目录会按名称自动识别；缺少的可在登记后补建。</small>
      </label>
      <template v-else>
        <p class="muted">先选择上级位置并填写名称，核对计划后再创建空目录。现有文件不会移动、改名或覆盖。</p>
        <label class="field">
          <span>上级文件夹</span>
          <input v-model="form.parent_dir" aria-label="上级文件夹" required autocomplete="off" :disabled="busy">
          <button type="button" :disabled="busy || picking" :aria-busy="picking" @click="pick">{{ picking ? '正在选择…' : '选择上级文件夹…' }}</button>
        </label>
        <label class="field"><span>新公司文件夹名称</span><input v-model="form.folder_name" aria-label="新公司文件夹名称" required maxlength="80" autocomplete="off" :disabled="busy"></label>
        <fieldset class="field">
          <legend>六类资料目录（可调整）</legend>
          <label v-for="item in standards" :key="item.key" class="field-row company-subdir-field">
            <span>{{ item.label }}</span><input v-model="subdirs[item.key]" :aria-label="`${item.label} 子目录`" required :disabled="busy" autocomplete="off">
          </label>
        </fieldset>
      </template>
      <fieldset class="field-row">
        <legend>纳税人身份（可稍后设置）</legend>
        <select v-model="form.taxpayer_type" aria-label="纳税人类型" :disabled="busy">
          <option value="">未设置</option><option value="general">一般纳税人</option><option value="small_scale">小规模纳税人</option>
        </select>
        <input v-model="form.effective_from" type="month" aria-label="生效月份" :disabled="busy || !form.taxpayer_type">
      </fieldset>
    </template>
    <section v-else class="panel" aria-label="新建工作区计划">
      <h3>{{ plan.state === 'prepared' ? '核对创建计划' : '创建结果' }}</h3>
      <p><strong>{{ plan.name }}</strong></p>
      <p class="path">{{ plan.root_path }}</p>
      <ul><li v-for="item in plan.items" :key="item.key">{{ item.label }} → {{ item.relative_path }}</li></ul>
      <p v-if="plan.state === 'prepared'" class="muted">确认后创建上述公司文件夹与六类空目录并登记；监控目录保持原样。</p>
      <p v-else role="status">{{ plan.message }}</p>
      <p v-if="plan.created.length" class="muted">已创建：{{ plan.created.join('、') }}</p>
      <p v-if="plan.state === 'unknown' || plan.state === 'failed'" class="muted">创建任务 {{ plan.job_id }}；已创建的目录保留，不会自动重试或删除。</p>
      <div class="actions">
        <button type="button" class="primary" :disabled="busy || plan.state === 'completed' || plan.state === 'failed'" :aria-busy="busy" @click="confirm">{{ submitted ? '读取执行结果' : '确认创建并登记' }}</button>
        <button v-if="!submitted" type="button" :disabled="busy" @click="plan = null">返回修改</button>
      </div>
    </section>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="banner banner--note" role="status">{{ notice }}</p>
    <div class="actions">
      <button v-if="!plan" type="submit" class="primary" :disabled="busy || picking" :aria-busy="busy">{{ busy ? '处理中…' : mode === 'existing' ? '登记' : '预览创建计划' }}</button>
      <button type="button" :disabled="busy" @click="emit('cancel')">{{ submitted ? '关闭' : '取消' }}</button>
    </div>
  </form>
</template>
