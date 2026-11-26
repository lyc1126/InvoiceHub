<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { Company, CostWorkbookRefresh, TaxpayerPeriod } from "../api/types";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { toast } from "../toast";
import CompanyDeleteModal from "./CompanyDeleteModal.vue";
import MonthPicker from "./MonthPicker.vue";

const props = defineProps<{ company: Company }>();
const companies = useCompaniesStore();
const standardSubdirs = computed(() => props.company.subdirs.filter((item) => item.kind !== "custom"));
const name = ref("");
const rootDir = ref("");
const baseRootDir = ref("");
const renameRootOnDisk = ref(false);
const newRootName = ref("");
const picking = ref(false);
const periods = ref<TaxpayerPeriod[]>([]);
const subdirs = ref<Record<string, string>>({});
// Baseline snapshot of standard subdir mappings when the draft was initialized or refreshed;
// lets us auto-sync untouched keys after a folder rename/promote without wiping unsaved edits.
const baseSubdirs = ref<Record<string, string>>({});
const busy = ref(false);
const error = ref("");
const notice = ref("");
const deleteModalOpen = ref(false);

function pathBasename(raw: string): string {
  const cleaned = raw.trim().replace(/[\\/]+$/, "");
  const parts = cleaned.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

const rootDirChanged = computed(() => rootDir.value.trim() !== baseRootDir.value.trim());

const staleMappingLabels = computed(() =>
  standardSubdirs.value
    .filter(
      (item) =>
        baseSubdirs.value[item.key] !== undefined
        && baseSubdirs.value[item.key] !== item.relative_path
        && subdirs.value[item.key] !== item.relative_path,
    )
    .map((item) => item.default_label || item.label),
);

function reset(): void {
  name.value = props.company.name;
  rootDir.value = props.company.root_path;
  baseRootDir.value = props.company.root_path;
  renameRootOnDisk.value = false;
  newRootName.value = pathBasename(props.company.root_path);
  const snapshot = Object.fromEntries(standardSubdirs.value.map((item) => [item.key, item.relative_path]));
  subdirs.value = { ...snapshot };
  baseSubdirs.value = { ...snapshot };
  periods.value = props.company.taxpayer_periods.map((item) => ({ ...item }));
  error.value = "";
  deleteModalOpen.value = false;
}

function workbookNotice(refresh: CostWorkbookRefresh | undefined): string {
  if (!refresh) return "";
  if (refresh.refreshed) return "当前监控目录的成本汇总表已按新的纳税人身份重写。";
  if (refresh.reason === "sync_running") return "监控目录正在同步，成本汇总表会在这次同步中按新身份写入。";
  return "";
}

async function pickRootDirectory(): Promise<void> {
  if (picking.value || busy.value) return;
  picking.value = true;
  error.value = "";
  try {
    const result = await companies.pickFolderDirectory();
    if (result.selected && result.path) {
      rootDir.value = result.path;
      renameRootOnDisk.value = false;
      notice.value = "已选择新的公司根目录，点击“保存”后生效（不会移动原文件）。";
    }
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    picking.value = false;
  }
}

async function openRootFolder(): Promise<void> {
  try {
    await companies.openCompanyRoot(props.company.id);
  } catch (cause) {
    toast(errorText(cause), "error", 4000);
  }
}

async function save(): Promise<void> {
  if (periods.value.some((item) => !item.effective_from)) {
    error.value = "请选择每条纳税人身份的生效月份。";
    return;
  }
  if (staleMappingLabels.value.length) {
    error.value = `资料目录映射（${staleMappingLabels.value.join("、")}）已在别处重命名或切换，请点击“放弃修改”刷新最新映射后再保存，避免覆盖新目录。`;
    return;
  }
  if (renameRootOnDisk.value && !newRootName.value.trim()) {
    error.value = "请填写新的硬盘公司文件夹名称。";
    return;
  }
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const changed = Object.fromEntries(
      standardSubdirs.value
        .filter((item) => subdirs.value[item.key] !== baseSubdirs.value[item.key] && subdirs.value[item.key] !== item.relative_path)
        .map((item) => [item.key, subdirs.value[item.key]!]),
    );
    const patch = {
      name: name.value,
      taxpayer_periods: periods.value,
      ...(Object.keys(changed).length ? { subdirs: changed } : {}),
      ...(rootDirChanged.value ? { root_dir: rootDir.value.trim() } : {}),
      ...(!rootDirChanged.value && renameRootOnDisk.value
        ? { rename_root_on_disk: true, new_root_name: newRootName.value.trim() }
        : {}),
    };
    const result = await companies.update(props.company.id, patch);
    await nextTick();
    reset(); // show the saved, backend-sorted values
    notice.value = ["已保存。", workbookNotice(result.cost_workbook)].join("");
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

// Only a different company resets the whole form; for the same company, keep unsaved drafts
// intact while syncing any untouched standard directory mapping after a disk rename or promote.
watch(() => props.company.id, () => {
  notice.value = "";
  reset();
}, { immediate: true });

watch(
  () => props.company.root_path,
  (nextRoot) => {
    if (!rootDirChanged.value) {
      rootDir.value = nextRoot;
      baseRootDir.value = nextRoot;
      if (!renameRootOnDisk.value) newRootName.value = pathBasename(nextRoot);
    }
  },
);

watch(
  () => standardSubdirs.value.map((item) => `${item.key}=${item.relative_path}`).join("\n"),
  () => {
    for (const item of standardSubdirs.value) {
      const key = item.key;
      const untouched = !(key in subdirs.value) || subdirs.value[key] === baseSubdirs.value[key];
      if (untouched) {
        subdirs.value[key] = item.relative_path;
        baseSubdirs.value[key] = item.relative_path;
      }
    }
  },
);
</script>

<template>
  <form class="panel" aria-label="公司设置" @submit.prevent="save">
    <label class="field">
      <span>公司名称</span>
      <input v-model="name" required maxlength="80" autocomplete="off" :disabled="busy">
    </label>

    <fieldset class="field">
      <legend>公司资料夹位置（重定位 / 硬盘改名）</legend>
      <p v-if="company.root_status !== 'present'" class="banner banner--error" role="alert">
        当前登记的文件夹路径在硬盘上不可用，请选择新的公司资料夹路径后点击“保存”完成重定位。
      </p>
      <p class="muted">更改路径仅重新绑定公司资料夹指向，不移动或删改原文件；如需直接把硬盘上的公司文件夹改名，请勾选下方选项。</p>
      <div class="field-row company-root-row">
        <input
          v-model="rootDir"
          class="mono"
          aria-label="公司资料夹路径"
          required
          autocomplete="off"
          :disabled="busy || picking || renameRootOnDisk"
        >
        <button type="button" :disabled="busy || picking || renameRootOnDisk" :aria-busy="picking" @click="pickRootDirectory">
          {{ picking ? "正在选择…" : "选择新文件夹…" }}
        </button>
        <button v-if="company.root_status === 'present'" type="button" class="ghost" :disabled="busy" @click="openRootFolder">
          打开文件夹
        </button>
      </div>
      <div class="company-disk-rename">
        <label class="company-check-row">
          <input
            v-model="renameRootOnDisk"
            type="checkbox"
            :disabled="busy || rootDirChanged || company.monitored || company.root_status !== 'present'"
          >
          <span>同时重命名硬盘上的公司根文件夹（同一上级目录内）</span>
        </label>
        <p v-if="company.monitored" class="muted">该公司下有目录正在监控，如需重命名硬盘公司文件夹请先切换监控目录。</p>
        <p v-else-if="rootDirChanged" class="muted">已修改上方根目录路径，如需重命名硬盘文件夹请先保存新路径后再单独改名。</p>
        <label v-if="renameRootOnDisk" class="field">
          <span>新的公司文件夹名</span>
          <input
            v-model="newRootName"
            class="mono"
            aria-label="新的公司文件夹名"
            required
            maxlength="80"
            autocomplete="off"
            :disabled="busy"
          >
        </label>
      </div>
    </fieldset>

    <fieldset class="field">
      <legend>资料目录映射</legend>
      <p class="muted">填写公司资料夹内的相对路径。保存只改变资料类型指向，不移动或重命名文件；缺少的目录可在“目录”里另行预览补建。</p>
      <label v-for="item in standardSubdirs" :key="item.key" class="field-row company-subdir-field">
        <span>{{ item.default_label || item.label }}</span><input v-model="subdirs[item.key]" :aria-label="`${item.default_label || item.label} 映射`" required autocomplete="off" :disabled="busy">
      </label>
    </fieldset>
    <fieldset class="field">
      <legend>纳税人身份</legend>
      <p class="muted">成本开票参考按本月生效的身份计算；未设置时不会默认按一般纳税人。</p>
      <div v-for="(period, index) in periods" :key="index" class="field-row">
        <MonthPicker v-model="period.effective_from" label="生效月份" placeholder="选择生效年月" :disabled="busy" />
        <span class="muted">起为</span>
        <select v-model="period.taxpayer_type" aria-label="纳税人类型">
          <option value="general">一般纳税人</option>
          <option value="small_scale">小规模纳税人</option>
        </select>
        <button type="button" :aria-label="`删除第 ${index + 1} 条`" @click="periods.splice(index, 1)">删除</button>
      </div>
      <button type="button" @click="periods.push({ effective_from: '', taxpayer_type: 'general' })">添加一条</button>
    </fieldset>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <div class="actions">
      <button type="submit" class="primary" :disabled="busy" :aria-busy="busy">保存</button>
      <button type="button" :disabled="busy" @click="reset">放弃修改</button>
    </div>
    <hr>
    <div class="actions company-danger-row">
      <div>
        <strong>移除或删除公司工作区</strong>
        <p class="muted">可选择“仅从清单移除（不删文件）”或“将整个公司资料夹移入系统回收站（二次确认）”。</p>
      </div>
      <button type="button" class="danger" :disabled="busy" @click="deleteModalOpen = true">移除 / 删除公司…</button>
    </div>

    <CompanyDeleteModal
      v-if="deleteModalOpen"
      :company="company"
      @close="deleteModalOpen = false"
      @done="deleteModalOpen = false"
    />
  </form>
</template>

<style scoped>
.company-root-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.company-root-row input { flex: 1 1 260px; }
.company-disk-rename { margin-top: 8px; display: grid; gap: 6px; }
.company-check-row { display: flex; align-items: center; gap: 8px; font-weight: 600; cursor: pointer; }
.company-danger-row { justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.company-danger-row p { margin: 2px 0 0; font-size: 12.5px; }
</style>
