<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { request } from "../api/client";
import type { Company, LedgerPayload, ProjectSummary } from "../api/types";
import { errorText, money, wan } from "../format";
import { companySourceKey, useCompaniesStore } from "../stores/companies";
import { useWorkspaceStore } from "../stores/workspace";
import WorkspaceIcon from "./WorkspaceIcon.vue";
import CompanyTax from "./CompanyTax.vue";
import OverviewDocuments from "./OverviewDocuments.vue";

const props = withDefaults(defineProps<{ company: Company; active?: boolean }>(), { active: true });
const emit = defineEmits<{ section: [name: "directories" | "ledger" | "projects" | "settings"] }>();
const companies = useCompaniesStore();
const workspace = useWorkspaceStore();
const refreshState = computed(() => companies.refreshStates[props.company.id]);
const refreshing = computed(() => refreshState.value?.status === "running");
const ledger = ref<LedgerPayload | null>(null);
const projects = ref<ProjectSummary | null>(null);
const period = ref("all");
const error = ref("");
const loading = ref(false);
let controller: AbortController | undefined;
let generation = 0;
const totals = computed(() => ledger.value?.totals);
const visibleSubdirs = computed(() => props.company.subdirs.filter(item => !item.hidden));
const complete = computed(() => visibleSubdirs.value.filter(item => item.status === "present").length);
// Labels name the concrete month / quarter like the prototype ("11 月 / 四季度 / 今年").
const today = new Date();
const periods = [
  { id: "month", label: `${today.getMonth() + 1} 月` },
  { id: "quarter", label: `${"一二三四"[Math.floor(today.getMonth() / 3)]}季度` },
  { id: "year", label: "今年" },
  { id: "all", label: "全部" },
];

// One range feeds the ledger, project and document reads so the three sections
// never describe different periods after a period switch.
const range = computed(() => {
  if (period.value === "all") return { start: "", end: "" };
  const now = new Date(), year = now.getFullYear(), month = now.getMonth() + 1;
  const start = period.value === "month" ? month : period.value === "quarter" ? Math.floor((month - 1) / 3) * 3 + 1 : 1;
  return { start: `${year}-${String(start).padStart(2, "0")}`, end: `${year}-${String(month).padStart(2, "0")}` };
});

async function load(): Promise<void> {
  const mine = ++generation;
  controller?.abort();
  controller = new AbortController();
  const signal = controller.signal;
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams({ granularity: "month" });
  if (range.value.start) query.set("start", range.value.start);
  if (range.value.end) query.set("end", range.value.end);
  // Both summaries keep the same company/range. Only server totals are displayed;
  // a partial failure preserves the other result and never turns unknown tax into zero.
  const base = `/api/v1/companies/${encodeURIComponent(props.company.id)}`;
  const results = await Promise.allSettled([
    request<LedgerPayload>(`${base}/ledger?${query}`, { signal }),
    request<ProjectSummary>(`${base}/projects?${query}`, { signal }),
  ]);
  if (mine !== generation || signal.aborted) return;
  const [book, project] = results;
  if (book.status === "fulfilled" && book.value.totals) ledger.value = book.value;
  else error.value = book.status === "rejected" ? errorText(book.reason) : "账簿结果暂不可用。";
  if (project.status === "fulfilled" && Array.isArray(project.value.projects)) projects.value = project.value;
  else error.value += `${error.value ? "；" : ""}项目汇总暂不可用。`;
  loading.value = false;
}

function onCompanyRefreshed(event: Event): void {
  const detail = (event as CustomEvent).detail;
  if (!detail?.companyId || detail.companyId === props.company.id) void load();
}
function refreshInvoices(): void {
  void companies.refreshData(props.company.id);
}

onMounted(() => window.addEventListener("workspace:company-refreshed", onCompanyRefreshed));
watch(() => companySourceKey(props.company), () => {
  ledger.value = null; projects.value = null; void load();
}, { immediate: true });
watch(period, () => { ledger.value = null; projects.value = null; void load(); });
onBeforeUnmount(() => { ++generation; controller?.abort(); window.removeEventListener("workspace:company-refreshed", onCompanyRefreshed); });
</script>

<template>
  <section class="company-overview" aria-label="公司总览">
    <div class="overview-tools">
      <div class="period-segment" role="group" aria-label="总览期间">
        <button v-for="item in periods" :key="item.id" type="button" :aria-pressed="period === item.id" @click="period = item.id">{{ item.label }}</button>
      </div>
    </div>
    <div class="overview-notice">
      <span>资料夹结构{{ complete === visibleSubdirs.length ? "齐全" : "待补充" }}（{{ complete }}/{{ visibleSubdirs.length }}）：{{ visibleSubdirs.filter(item => item.status === "present").map(item => item.label).join("、") || "尚未找到资料目录" }}。</span>
      <button type="button" :disabled="refreshing" :aria-busy="refreshing" @click="refreshInvoices">{{ refreshing ? "读取中…" : "更新发票数据" }}</button>
      <button type="button" @click="emit('section', 'directories')">查看资料夹</button>
    </div>
    <p v-if="refreshing" class="banner banner--note" role="status" aria-busy="true">{{ refreshState?.message || "正在后台读取发票数据…" }}</p>
    <p class="overview-notice"><span>票面口径：按本公司各目录已识别的发票统计，<b>不是会计利润，也不是应纳税额</b>；未识别或待核对的发票暂不计入。</span></p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="ledger && !ledger.checks_ok" class="banner banner--error" role="alert">金额核对有出入，结果暂不可用。{{ (ledger.checks ?? []).filter(item => !item.ok).map(item => item.message).join("；") }}</p>
    <section class="overview-section" aria-label="票面指标">
      <div class="overview-kpis">
        <div class="overview-kpi overview-kpi--key"><span>销项收入（不含税）</span><strong :title="totals && ledger?.checks_ok ? money(totals.output.pretax) : undefined">{{ totals && ledger?.checks_ok ? wan(totals.output.pretax) : "—" }}</strong><small>开具发票票面</small></div>
        <div class="overview-kpi"><span>进项成本（不含税）</span><strong :title="totals && ledger?.checks_ok ? money(totals.input.pretax) : undefined">{{ totals && ledger?.checks_ok ? wan(totals.input.pretax) : "—" }}</strong><small>成本发票票面</small></div>
        <div class="overview-kpi overview-kpi--key"><span>票面毛利</span><strong :title="totals && ledger?.checks_ok ? money(totals.face_difference_pretax) : undefined">{{ totals && ledger?.checks_ok ? wan(totals.face_difference_pretax) : "—" }}</strong><small>销项与进项不含税差额</small></div>
        <div class="overview-kpi"><span>销项税额</span><strong :title="totals && ledger?.checks_ok ? money(totals.output.tax) : undefined">{{ totals && ledger?.checks_ok ? wan(totals.output.tax) : "—" }}</strong><small>已识别发票税额</small></div>
        <div class="overview-kpi"><span>可抵扣进项税额</span><strong>{{ company.current_taxpayer_type === 'small_scale' ? "不适用" : "—" }}</strong><small>{{ company.current_taxpayer_type === 'small_scale' ? "小规模纳税人不抵扣" : "以抵扣清单核对为准" }}</small></div>
        <div class="overview-kpi"><span>发票张数</span><strong>{{ totals && ledger?.checks_ok ? `进 ${totals.input.count} / 销 ${totals.output.count}` : "—" }}</strong><small>同一张票多格式只算一次</small></div>
      </div>
      <CompanyTax :company="company" :start="range.start" :end="range.end" compact />
    </section>
    <section class="overview-section">
      <header class="overview-section__head"><div><h3>按月</h3><p>每一行都可对照当月的原始发票。</p></div><button type="button" @click="emit('section', 'ledger')">查看完整账簿</button></header>
      <div class="overview-table-wrap"><table class="grid" aria-label="按月票面汇总">
        <thead><tr><th>月份</th><th class="num">销项收入</th><th class="num">进项成本</th><th class="num">票面毛利</th><th class="num">销项税额</th><th class="num">进项票面税额</th><th class="num">张数（进 / 销）</th><th>状态</th></tr></thead>
        <tbody><tr v-for="row in ledger?.periods ?? []" :key="row.period"><td>{{ row.period }}</td><td class="num">{{ money(row.output.pretax) }}</td><td class="num">{{ money(row.input.pretax) }}</td><td class="num">{{ money(row.face_difference_pretax) }}</td><td class="num">{{ money(row.output.tax) }}</td><td class="num">{{ money(row.input.tax) }}</td><td class="num">{{ row.input.count }} / {{ row.output.count }}</td><td><span class="tag" :class="ledger?.checks_ok ? 'pill-ok' : 'tag--danger'">{{ ledger?.checks_ok ? "已汇总" : "待核对" }}</span></td></tr>
          <tr v-if="!ledger?.periods?.length"><td colspan="8" class="overview-empty">{{ loading ? "正在读取已识别发票…" : error ? "读取未完成，请重试" : "所选期间没有可汇总的发票" }}</td></tr></tbody>
        <tfoot v-if="totals"><tr><th>合计</th><td class="num">{{ money(totals.output.pretax) }}</td><td class="num">{{ money(totals.input.pretax) }}</td><td class="num">{{ money(totals.face_difference_pretax) }}</td><td class="num">{{ money(totals.output.tax) }}</td><td class="num">{{ money(totals.input.tax) }}</td><td class="num">{{ totals.input.count }} / {{ totals.output.count }}</td><td /></tr></tfoot>
      </table></div>
    </section>
    <section class="overview-section">
      <header class="overview-section__head"><div><h3>按项目</h3><p>项目取自发票备注“项目名称”；未归属的单独列出，不平均摊。</p></div><button type="button" @click="emit('section', 'projects')">管理项目归属</button></header>
      <div class="overview-table-wrap"><table class="grid" aria-label="总览项目汇总"><thead><tr><th>项目</th><th class="num">收入（不含税）</th><th class="num">成本（不含税）</th><th class="num">票面毛利</th><th /></tr></thead><tbody>
        <tr v-for="row in projects?.projects ?? []" :key="row.project"><td><WorkspaceIcon name="project" /> {{ row.unassigned ? "未归属项目" : row.project }}</td><td class="num">{{ money(row.output.pretax) }}</td><td class="num">{{ money(row.input.pretax) }}</td><td class="num">{{ money(row.face_difference_pretax) }}</td><td><button type="button" class="link" @click="row.unassigned ? emit('section', 'projects') : workspace.open({ kind: 'project', companyId: company.id, project: row.project })">{{ row.unassigned ? "去指派" : "打开 ›" }}</button></td></tr>
        <tr v-if="!projects?.projects?.length"><td colspan="5" class="overview-empty">暂无项目汇总</td></tr>
      </tbody></table></div>
    </section>
    <OverviewDocuments :company="company" :start="range.start" :end="range.end" :active="active" />
    <section class="overview-section"><header class="overview-section__head"><div><h3>资料目录</h3><p>原始文件保存在公司资料夹或已导入目录里，点下方目录即可查看。</p></div></header><div class="overview-sources"><button v-for="dir in visibleSubdirs" :key="dir.key" type="button" :disabled="dir.status !== 'present'" @click="workspace.open({ kind: 'directory', companyId: company.id, dirKey: dir.key })"><WorkspaceIcon :name="(dir.role || dir.key) === 'bank_flow_dir' ? 'bank' : 'folder'" />{{ dir.label }}<small>{{ dir.status === 'present' ? '打开 ›' : '缺失' }}</small></button></div></section>
  </section>
</template>
