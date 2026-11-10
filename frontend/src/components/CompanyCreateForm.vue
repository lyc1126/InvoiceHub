<script setup lang="ts">
import { reactive, ref } from "vue";
import type { TaxpayerType } from "../api/types";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";

const emit = defineEmits<{ created: [sources: Record<string, string>]; cancel: [] }>();
const companies = useCompaniesStore();
const form = reactive({ name: "", root_dir: "", taxpayer_type: "" as TaxpayerType | "", effective_from: "" });
const busy = ref(false);
const error = ref("");

async function submit(): Promise<void> {
  error.value = "";
  if (form.taxpayer_type && !form.effective_from) {
    error.value = "请填写纳税人身份的生效月份。";
    return;
  }
  busy.value = true;
  try {
    const result = await companies.create({
      name: form.name,
      root_dir: form.root_dir,
      // Left empty the type stays 未设置; it is never assumed to be 一般纳税人.
      taxpayer_periods: form.taxpayer_type ? [{ effective_from: form.effective_from, taxpayer_type: form.taxpayer_type }] : [],
    });
    Object.assign(form, { name: "", root_dir: "", taxpayer_type: "", effective_from: "" });
    emit("created", result.subdir_sources ?? {});
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <form class="panel" aria-label="新建公司" @submit.prevent="submit">
    <h2>新建公司</h2>
    <label class="field">
      <span>公司名称</span>
      <input v-model="form.name" required maxlength="80" autocomplete="off">
    </label>
    <label class="field">
      <span>公司资料夹</span>
      <input v-model="form.root_dir" required placeholder="粘贴已存在的文件夹路径" autocomplete="off">
      <small class="muted">成本发票、开具发票等子目录会按名称自动识别；缺少的可在登记后补建。</small>
    </label>
    <fieldset class="field-row">
      <legend>纳税人身份（可稍后设置）</legend>
      <select v-model="form.taxpayer_type" aria-label="纳税人类型">
        <option value="">未设置</option>
        <option value="general">一般纳税人</option>
        <option value="small_scale">小规模纳税人</option>
      </select>
      <input v-model="form.effective_from" type="month" aria-label="生效月份" :disabled="!form.taxpayer_type">
    </fieldset>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <div class="actions">
      <button type="submit" class="primary" :disabled="busy" :aria-busy="busy">{{ busy ? "登记中…" : "登记" }}</button>
      <button type="button" :disabled="busy" @click="emit('cancel')">取消</button>
    </div>
  </form>
</template>
