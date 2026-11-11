<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company, ProjectInvoice, ProjectSummary } from "../api/types";
import { errorText, money } from "../format";

// `focus` is the project a sidebar node opened: its row is marked and its periods listed.
const props = defineProps<{ company: Company; focus?: string }>();
const filters = reactive({ granularity: "month", start: "", end: "" });
const summary = ref<ProjectSummary | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");
// Draft values keyed by invoice number; only changed rows are sent.
const drafts = reactive<Record<string, string>>({});
const base = computed(() => `/api/v1/companies/${encodeURIComponent(props.company.id)}/projects`);
const changed = computed(() => Object.entries(drafts).filter(([number, value]) => value.trim() !== (original.value[number] ?? "")));
const original = computed<Record<string, string>>(() => {
  const values: Record<string, string> = {};
  for (const item of summary.value?.manual_invoices ?? []) values[item.invoice_number] = item.project;
  return values;
});
const focused = computed(() => (props.focus ? summary.value?.projects.find((row) => !row.unassigned && row.project === props.focus) ?? null : null));
const SOURCE: Record<ProjectInvoice["source"], string> = {
  remark: "备注",
  manual: "人工",
  conflict: "备注不一致",
  none: "备注无项目",
};

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams({ granularity: filters.granularity });
  if (filters.start) query.set("start", filters.start);
  if (filters.end) query.set("end", filters.end);
  try {
    summary.value = await request<ProjectSummary>(`${base.value}?${query}`);
    for (const key of Object.keys(drafts)) delete drafts[key];
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    loading.value = false;
  }
}

async function save(): Promise<void> {
  if (!summary.value || !changed.value.length) return;
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    const assignments = Object.fromEntries(changed.value.map(([number, value]) => [number, value.trim()]));
    await request(`${base.value}/assignments`, {
      method: "PUT",
      body: { revision: summary.value.assignments_revision, assignments },
    });
    notice.value = `已保存 ${changed.value.length} 张发票的项目归属。`;
    await load();
  } catch (cause) {
    // Someone else saved first: reload instead of overwriting, and keep the message visible.
    if (cause instanceof ApiError && cause.code === "COMPANY_PROJECTS_CONFLICT") {
      await load();
      error.value = "项目归属已被修改，已刷新，请重新填写。";
    } else {
      error.value = errorText(cause);
    }
  } finally {
    saving.value = false;
  }
}

watch(
  () => props.company.id,
  () => {
    summary.value = null;
    notice.value = "";
    void load();
  },
  { immediate: true },
);
</script>

<template>
  <section aria-label="项目">
    <form class="toolbar" @submit.prevent="load">
      <select v-model="filters.granularity" aria-label="汇总粒度">
        <option value="month">按月</option>
        <option value="quarter">按季</option>
        <option value="year">按年</option>
      </select>
      <input v-model="filters.start" type="month" aria-label="开始月份">
      <span class="muted">至</span>
      <input v-model="filters.end" type="month" aria-label="结束月份">
      <button type="submit" :disabled="loading" :aria-busy="loading">{{ loading ? "计算中…" : "查询" }}</button>
    </form>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>

    <template v-if="summary">
      <p class="banner banner--note">{{ summary.basis_label }}</p>
      <details class="checks" :class="{ 'checks--failed': !summary.checks_ok }" :open="!summary.checks_ok" role="status">
        <summary><strong>{{ summary.checks_ok ? `与发票账簿一致（${summary.checks.length} 项）` : "与发票账簿不一致" }}</strong></summary>
        <ul>
          <li v-for="check in summary.checks" :key="check.code" :class="{ 'check--failed': !check.ok }">{{ check.ok ? "✓" : "✗" }} {{ check.message }}</li>
        </ul>
      </details>
      <ul v-if="summary.warnings.length" class="warnings warnings--compact">
        <li v-for="warning in summary.warnings" :key="warning.code">{{ warning.message }}</li>
      </ul>

      <table class="grid ledger" aria-label="项目汇总">
        <thead>
          <tr>
            <th rowspan="2">项目</th><th colspan="2">进项（成本发票）</th><th colspan="2">销项（开具发票）</th><th rowspan="2" class="num">票面差额（不含税）</th>
          </tr>
          <tr><th class="num">张数</th><th class="num">价税合计</th><th class="num">张数</th><th class="num">价税合计</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in summary.projects" :key="row.project" :class="{ 'row--muted': row.unassigned, 'row--active': !row.unassigned && row.project === focus }">
            <th scope="row">{{ row.unassigned ? "未归属" : row.project }}</th>
            <td class="num">{{ row.input.count }}</td><td class="num">{{ money(row.input.total) }}</td>
            <td class="num">{{ row.output.count }}</td><td class="num">{{ money(row.output.total) }}</td>
            <td class="num">{{ money(row.face_difference_pretax) }}</td>
          </tr>
        </tbody>
      </table>

      <table v-if="focused" class="grid ledger" :aria-label="`${focused.project} 各期`">
        <caption>{{ focused.project }} · 各期不含税金额</caption>
        <thead><tr><th>期间</th><th class="num">进项</th><th class="num">销项</th></tr></thead>
        <tbody>
          <tr v-for="period in focused.periods" :key="period.period">
            <td class="nowrap">{{ period.period }}</td><td class="num">{{ money(period.input_pretax) }}</td><td class="num">{{ money(period.output_pretax) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="focus" class="muted">所选期间没有“{{ focus }}”的发票。</p>

      <datalist id="company-project-names">
        <option v-for="name in summary.project_names" :key="name" :value="name" />
      </datalist>
      <form v-if="summary.unassigned_invoices.length || summary.manual_invoices.length" class="panel" aria-label="项目归属" @submit.prevent="save">
        <h3>指定项目（人工值优先于备注，重新汇总不会覆盖；留空即恢复按备注）</h3>
        <table class="grid">
          <thead><tr><th>方向</th><th>发票号码</th><th>开票日期</th><th>对方</th><th class="num">价税合计</th><th>现在</th><th>项目</th></tr></thead>
          <tbody>
            <tr v-for="item in [...summary.unassigned_invoices, ...summary.manual_invoices]" :key="item.direction + item.invoice_number + item.source_files.join()">
              <td class="nowrap">{{ item.direction === "input" ? "进项" : "销项" }}</td>
              <td>{{ item.invoice_number || "—" }}</td>
              <td class="nowrap">{{ item.invoice_date }}</td>
              <td>{{ item.counterpart }}</td>
              <td class="num">{{ money(item.total) }}</td>
              <td class="nowrap" :title="item.remark_projects.join('、')">{{ SOURCE[item.source] }}</td>
              <td>
                <input
                  v-if="item.assignable"
                  :value="drafts[item.invoice_number] ?? (item.source === 'manual' ? item.project : '')"
                  list="company-project-names"
                  maxlength="60"
                  :aria-label="`${item.invoice_number} 项目`"
                  @input="drafts[item.invoice_number] = ($event.target as HTMLInputElement).value"
                >
                <span v-else class="muted">无发票号码，不能指定</span>
              </td>
            </tr>
          </tbody>
        </table>
        <button type="submit" class="primary" :disabled="saving || !changed.length" :aria-busy="saving">
          {{ saving ? "保存中…" : `保存（${changed.length}）` }}
        </button>
      </form>
    </template>
  </section>
</template>
