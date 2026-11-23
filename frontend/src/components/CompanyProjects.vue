<script setup lang="ts">
import { companySourceKey } from "../stores/companies";
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company, ProjectInvoice, ProjectRenameResult, ProjectSummary } from "../api/types";
import { errorText, money } from "../format";
import ProjectRenameModal from "./ProjectRenameModal.vue";

// `focus` is the project a sidebar node opened: its row is marked and its periods listed.
const props = defineProps<{ company: Company; focus?: string }>();
const filters = reactive({ granularity: "month", start: "", end: "" });
const summary = ref<ProjectSummary | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");
// Draft values keyed by invoice number: string assigns/restores (`""` restores remark),
// while `unassignedDraft` marks invoices explicitly moved to 未归属 (overriding remark).
const drafts = reactive<Record<string, string>>({});
const unassignedDraft = reactive<Record<string, boolean>>({});
const sourcesStale = ref(false);
const scopeFilter = ref<"all" | "unassigned" | "remark" | "manual">("all");
const projectFilter = ref("");
const invoiceKeyword = ref("");
const renaming = ref<string | null>(null);
const base = computed(() => `/api/v1/companies/${encodeURIComponent(props.company.id)}/projects`);

// Full invoice list for manual adjustments; falls back to unassigned+manual for legacy fixtures.
const allInvoices = computed<ProjectInvoice[]>(() => {
  if (!summary.value) return [];
  if (Array.isArray(summary.value.invoices)) return summary.value.invoices;
  return [...summary.value.unassigned_invoices, ...summary.value.manual_invoices];
});

const byNumber = computed<Record<string, ProjectInvoice>>(() => {
  const map: Record<string, ProjectInvoice> = {};
  for (const item of allInvoices.value) {
    if (item.invoice_number) map[item.invoice_number] = item;
  }
  return map;
});

const changedAssignments = computed<[string, string][]>(() => {
  const out: [string, string][] = [];
  for (const [number, raw] of Object.entries(drafts)) {
    if (unassignedDraft[number]) continue;
    const next = raw.trim();
    const item = byNumber.value[number];
    if (!item) continue;
    // Empty string clears a manual override (restoring remark); non-empty sets a manual project.
    if (next === "") {
      if (item.source === "manual") out.push([number, ""]);
    } else if (next !== item.project || item.source !== "manual") {
      out.push([number, next]);
    }
  }
  return out;
});

const changedUnassigned = computed<string[]>(() =>
  Object.keys(unassignedDraft).filter((number) => {
    if (!unassignedDraft[number]) return false;
    const item = byNumber.value[number];
    return !!item && !(item.source === "manual" && item.project === "");
  }),
);

const changeCount = computed(() => changedAssignments.value.length + changedUnassigned.value.length);

const filteredInvoices = computed<ProjectInvoice[]>(() => {
  const kw = invoiceKeyword.value.trim().toLocaleLowerCase();
  return allInvoices.value.filter((item) => {
    if (scopeFilter.value === "unassigned" && item.project !== "") return false;
    if (scopeFilter.value === "remark" && item.source !== "remark") return false;
    if (scopeFilter.value === "manual" && item.source !== "manual") return false;
    if (projectFilter.value === "__unassigned__" && item.project !== "") return false;
    if (projectFilter.value && projectFilter.value !== "__unassigned__" && item.project !== projectFilter.value) return false;
    if (!kw) return true;
    return [item.invoice_number, item.counterpart, item.project, ...item.remark_projects]
      .some((value) => String(value || "").toLocaleLowerCase().includes(kw));
  });
});

const focused = computed(() => (props.focus ? summary.value?.projects.find((row) => !row.unassigned && row.project === props.focus) ?? null : null));
const SOURCE: Record<ProjectInvoice["source"], string> = {
  remark: "备注",
  manual: "人工",
  conflict: "备注不一致",
  none: "备注无项目",
};

function clearDrafts(): void {
  for (const key of Object.keys(drafts)) delete drafts[key];
  for (const key of Object.keys(unassignedDraft)) delete unassignedDraft[key];
}

function inputValue(item: ProjectInvoice): string {
  if (unassignedDraft[item.invoice_number]) return "";
  if (item.invoice_number in drafts) return drafts[item.invoice_number] ?? "";
  return item.project;
}

function onProjectInput(item: ProjectInvoice, value: string): void {
  delete unassignedDraft[item.invoice_number];
  drafts[item.invoice_number] = value;
}

function toggleUnassign(item: ProjectInvoice): void {
  const number = item.invoice_number;
  if (unassignedDraft[number]) {
    delete unassignedDraft[number];
    return;
  }
  delete drafts[number];
  unassignedDraft[number] = true;
}

function restoreRemark(item: ProjectInvoice): void {
  delete unassignedDraft[item.invoice_number];
  drafts[item.invoice_number] = "";
}

function selectProjectRow(project: string, isUnassigned: boolean): void {
  const next = isUnassigned ? "__unassigned__" : project;
  projectFilter.value = projectFilter.value === next ? "" : next;
  scopeFilter.value = "all";
}

let loadGeneration = 0;
async function load(): Promise<void> {
  const mine = ++loadGeneration;
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams({ granularity: filters.granularity });
  if (filters.start) query.set("start", filters.start);
  if (filters.end) query.set("end", filters.end);
  try {
    const next = await request<ProjectSummary>(`${base.value}?${query}`);
    if (mine !== loadGeneration) return;
    summary.value = next;
    sourcesStale.value = false;
    clearDrafts();
  } catch (cause) {
    if (mine === loadGeneration) error.value = errorText(cause);
  } finally {
    if (mine === loadGeneration) loading.value = false;
  }
}

async function save(): Promise<void> {
  if (!summary.value || !changeCount.value || sourcesStale.value) return;
  saving.value = true;
  error.value = "";
  notice.value = "";
  const savedTotal = changeCount.value;
  try {
    const body: Record<string, unknown> = { revision: summary.value.assignments_revision };
    if (changedAssignments.value.length) {
      body.assignments = Object.fromEntries(changedAssignments.value);
    }
    if (changedUnassigned.value.length) {
      body.unassigned = changedUnassigned.value;
    }
    await request(`${base.value}/assignments`, { method: "PUT", body });
    notice.value = `已保存 ${savedTotal} 张发票的项目归属。`;
    await load();
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id } }));
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

async function onRenamed(result: ProjectRenameResult): Promise<void> {
  renaming.value = null;
  if (projectFilter.value === result.from_name) projectFilter.value = result.to_name;
  notice.value = `已将项目「${result.from_name}」重命名为「${result.to_name}」${result.service_costs_updated ? `（同步更新 ${result.service_costs_updated} 条服务成本）` : ""}。`;
  await load();
  window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.company.id, renamedFrom: result.from_name, renamedTo: result.to_name } }));
}

function onCompanyRefreshed(event: Event): void {
  const detail = (event as CustomEvent).detail;
  if (!detail?.companyId || detail.companyId === props.company.id) {
    if (!changeCount.value) void load();
  }
}

onMounted(() => window.addEventListener("workspace:company-refreshed", onCompanyRefreshed));
onBeforeUnmount(() => window.removeEventListener("workspace:company-refreshed", onCompanyRefreshed));

watch(() => props.focus, (value) => {
  if (value) {
    projectFilter.value = value;
    scopeFilter.value = "all";
  }
}, { immediate: true });

watch(
  () => companySourceKey(props.company, ["cost_invoice_dir", "issued_invoice_dir"]),
  (_value, previous) => {
    if (previous && JSON.parse(previous)[0] === props.company.id && changeCount.value) { sourcesStale.value = true; loadGeneration += 1; loading.value = false; return; }
    summary.value = null;
    notice.value = "";
    void load();
  },
  { immediate: true },
);
</script>

<template>
  <section aria-label="项目">
    <p v-if="sourcesStale" class="banner banner--note" role="status">目录映射已变化，未保存的项目归属已保留。<button type="button" :disabled="loading" @click="load">放弃未保存归属并重读</button></p>
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
            <th rowspan="2">项目</th><th colspan="2">进项（成本发票）</th><th colspan="2">销项（开具发票）</th><th rowspan="2" class="num">票面差额（不含税）</th><th rowspan="2">操作</th>
          </tr>
          <tr><th class="num">张数</th><th class="num">价税合计</th><th class="num">张数</th><th class="num">价税合计</th></tr>
        </thead>
        <tbody>
          <tr
            v-for="row in summary.projects"
            :key="row.project"
            :class="{ 'row--muted': row.unassigned, 'row--active': (!row.unassigned && (row.project === focus || row.project === projectFilter)) || (row.unassigned && projectFilter === '__unassigned__') }"
          >
            <th scope="row">
              <button type="button" class="link" @click="selectProjectRow(row.project, row.unassigned)">
                {{ row.unassigned ? "未归属" : row.project }}
              </button>
            </th>
            <td class="num">{{ row.input.count }}</td><td class="num">{{ money(row.input.total) }}</td>
            <td class="num">{{ row.output.count }}</td><td class="num">{{ money(row.output.total) }}</td>
            <td class="num">{{ money(row.face_difference_pretax) }}</td>
            <td class="nowrap">
              <button
                v-if="!row.unassigned"
                type="button"
                class="ghost"
                :aria-label="`重命名 ${row.project}`"
                @click="renaming = row.project"
              >重命名…</button>
              <span v-else class="muted">—</span>
            </td>
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
      <form v-if="allInvoices.length" class="panel" aria-label="项目归属" @submit.prevent="save">
        <h3>指定与调整项目归属（支持调整任意发票；人工值优先于备注，重新汇总不会覆盖）</h3>
        <div class="filters">
          <label class="field">来源
            <select v-model="scopeFilter" aria-label="按归属来源筛选">
              <option value="all">全部（{{ allInvoices.length }}）</option>
              <option value="unassigned">未归属（{{ summary.unassigned_invoices.length }}）</option>
              <option value="remark">备注识别（{{ allInvoices.filter((item) => item.source === 'remark').length }}）</option>
              <option value="manual">人工指定（{{ summary.manual_invoices.length }}）</option>
            </select>
          </label>
          <label class="field">项目
            <select v-model="projectFilter" aria-label="按项目筛选">
              <option value="">全部项目</option>
              <option value="__unassigned__">未归属</option>
              <option v-for="name in summary.project_names" :key="name" :value="name">{{ name }}</option>
            </select>
          </label>
          <label class="field">搜索
            <input v-model="invoiceKeyword" type="search" placeholder="发票号 / 对方 / 项目名" aria-label="搜索项目发票">
          </label>
        </div>
        <table class="grid">
          <thead><tr><th>方向</th><th>发票号码</th><th>开票日期</th><th>对方</th><th class="num">价税合计</th><th>现在</th><th>项目</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="item in filteredInvoices" :key="item.direction + item.invoice_number + item.source_files.join()">
              <td class="nowrap">{{ item.direction === "input" ? "进项" : "销项" }}</td>
              <td>{{ item.invoice_number || "—" }}</td>
              <td class="nowrap">{{ item.invoice_date }}</td>
              <td>{{ item.counterpart }}</td>
              <td class="num">{{ money(item.total) }}</td>
              <td class="nowrap" :title="item.remark_projects.join('、')">
                {{ unassignedDraft[item.invoice_number] ? "待移出未归属" : SOURCE[item.source] }}
              </td>
              <td>
                <input
                  v-if="item.assignable"
                  :value="inputValue(item)"
                  list="company-project-names"
                  maxlength="60"
                  placeholder="输入或选择项目名称"
                  :aria-label="`${item.invoice_number} 项目`"
                  @input="onProjectInput(item, ($event.target as HTMLInputElement).value)"
                >
                <span v-else class="muted">无发票号码，不能指定</span>
              </td>
              <td class="nowrap">
                <template v-if="item.assignable">
                  <button
                    v-if="item.project || unassignedDraft[item.invoice_number]"
                    type="button"
                    class="ghost"
                    @click="toggleUnassign(item)"
                  >{{ unassignedDraft[item.invoice_number] ? "撤销移出" : "移出未归属" }}</button>
                  <button
                    v-if="item.source === 'manual' && item.remark_projects.length"
                    type="button"
                    class="ghost"
                    @click="restoreRemark(item)"
                  >恢复备注</button>
                </template>
                <span v-else class="muted">—</span>
              </td>
            </tr>
            <tr v-if="!filteredInvoices.length">
              <td colspan="8" class="muted">当前筛选条件下没有发票。</td>
            </tr>
          </tbody>
        </table>
        <button type="submit" class="primary" :disabled="saving || !changeCount || sourcesStale" :aria-busy="saving">
          {{ saving ? "保存中…" : `保存（${changeCount}）` }}
        </button>
      </form>
    </template>

    <ProjectRenameModal
      v-if="renaming && summary"
      :company-id="company.id"
      :company-name="company.name"
      :from-name="renaming"
      :revision="summary.assignments_revision"
      :project-names="summary.project_names"
      @close="renaming = null"
      @done="onRenamed"
    />
  </section>
</template>
