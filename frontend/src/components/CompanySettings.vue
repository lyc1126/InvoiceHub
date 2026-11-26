<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { Company, CostWorkbookRefresh, TaxpayerPeriod } from "../api/types";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";
import MonthPicker from "./MonthPicker.vue";

const props = defineProps<{ company: Company }>();
const companies = useCompaniesStore();
const standardSubdirs = computed(() => props.company.subdirs.filter((item) => item.kind !== "custom"));
const name = ref("");
const periods = ref<TaxpayerPeriod[]>([]);
const subdirs = ref<Record<string, string>>({});
// Baseline snapshot of standard subdir mappings when the draft was initialized or refreshed;
// lets us auto-sync untouched keys after a folder rename/promote without wiping unsaved edits.
const baseSubdirs = ref<Record<string, string>>({});
const busy = ref(false);
const error = ref("");
const notice = ref("");
const confirmRemove = ref(false);

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
  const snapshot = Object.fromEntries(standardSubdirs.value.map((item) => [item.key, item.relative_path]));
  subdirs.value = { ...snapshot };
  baseSubdirs.value = { ...snapshot };
  periods.value = props.company.taxpayer_periods.map((item) => ({ ...item }));
  error.value = "";
  confirmRemove.value = false;
}

function workbookNotice(refresh: CostWorkbookRefresh | undefined): string {
  if (!refresh) return "";
  if (refresh.refreshed) return "当前监控目录的成本汇总表已按新的纳税人身份重写。";
  if (refresh.reason === "sync_running") return "监控目录正在同步，成本汇总表会在这次同步中按新身份写入。";
  return "";
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
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const changed = Object.fromEntries(
      standardSubdirs.value
        .filter((item) => subdirs.value[item.key] !== baseSubdirs.value[item.key] && subdirs.value[item.key] !== item.relative_path)
        .map((item) => [item.key, subdirs.value[item.key]!]),
    );
    const result = await companies.update(props.company.id, { name: name.value, taxpayer_periods: periods.value,
      ...(Object.keys(changed).length ? { subdirs: changed } : {}) });
    await nextTick();
    reset(); // show the saved, backend-sorted values
    notice.value = ["已保存。", workbookNotice(result.cost_workbook)].join("");
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

async function remove(): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    await companies.remove(props.company.id);
  } catch (cause) {
    error.value = errorText(cause);
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
      <input v-model="name" required maxlength="80" autocomplete="off">
    </label>
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
    <div v-if="!confirmRemove" class="actions">
      <button type="button" class="danger" :disabled="busy" @click="confirmRemove = true">从清单移除</button>
    </div>
    <div v-else class="actions" role="alertdialog" aria-label="确认移除">
      <span>只移除这条登记，公司资料夹里的文件一个都不会删除。</span>
      <button type="button" class="danger" :disabled="busy" :aria-busy="busy" @click="remove">确认移除</button>
      <button type="button" :disabled="busy" @click="confirmRemove = false">取消</button>
    </div>
  </form>
</template>
