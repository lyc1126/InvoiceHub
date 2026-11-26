<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { request } from "../api/client";
import type {
  WorkspaceSearchDirectoryHit,
  WorkspaceSearchInvoiceHit,
  WorkspaceSearchPayload,
  WorkspaceSearchProjectHit,
} from "../api/types";
import { errorText, money } from "../format";
import { useCompaniesStore } from "../stores/companies";
import { useWorkspaceStore } from "../stores/workspace";
import WsModal from "./WsModal.vue";

// Read-only cross-directory / cross-company search modal (WS-11).
// Queries only already-built projections and cached project/tag metadata; clicking a hit
// opens the target company directory or project tab without switching the active watch_dir.
const emit = defineEmits<{ close: []; navigateHome: [] }>();
const companies = useCompaniesStore();
const workspace = useWorkspaceStore();

const inputRef = ref<HTMLInputElement | null>(null);
const q = ref(workspace.globalSearchSeed || "");
const scope = ref<"all" | "company">("all");
const companyId = ref(workspace.active?.companyId || companies.companies[0]?.id || "");
const searchScope = ref<"workspace" | "party" | "buyer" | "invoice" | "filename">("workspace");
const roleFilter = ref("");
const advancedOpen = ref(false);
const dateFrom = ref("");
const dateTo = ref("");
const amountMin = ref("");
const amountMax = ref("");
const sortBy = ref<"invoice_date" | "amount">("invoice_date");
const sortDir = ref<"desc" | "asc">("desc");

const loading = ref(false);
const error = ref("");
const payload = ref<WorkspaceSearchPayload | null>(null);

let reqGen = 0;
let timer: ReturnType<typeof setTimeout> | undefined;

const hasActiveFilters = computed(() =>
  Boolean(q.value.trim() || roleFilter.value || dateFrom.value || dateTo.value || amountMin.value.trim() || amountMax.value.trim()),
);

async function runSearch(): Promise<void> {
  clearTimeout(timer);
  const mine = ++reqGen;
  loading.value = true;
  error.value = "";
  const params = new URLSearchParams();
  if (q.value.trim()) params.set("q", q.value.trim());
  params.set("search_scope", searchScope.value);
  params.set("scope", scope.value);
  if (scope.value === "company" && companyId.value) params.set("company_id", companyId.value);
  if (roleFilter.value) params.set("role", roleFilter.value);
  if (dateFrom.value) params.set("date_from", dateFrom.value);
  if (dateTo.value) params.set("date_to", dateTo.value);
  if (amountMin.value.trim()) params.set("amount_min", amountMin.value.trim());
  if (amountMax.value.trim()) params.set("amount_max", amountMax.value.trim());
  params.set("sort_by", sortBy.value);
  params.set("sort_dir", sortDir.value);
  params.set("limit", "100");
  try {
    const res = await request<WorkspaceSearchPayload>(`/api/v1/workspace/search?${params.toString()}`);
    if (mine !== reqGen) return;
    payload.value = res;
  } catch (cause) {
    if (mine === reqGen) error.value = errorText(cause);
  } finally {
    if (mine === reqGen) loading.value = false;
  }
}

function scheduleSearch(): void {
  clearTimeout(timer);
  timer = setTimeout(() => void runSearch(), 220);
}

function resetFilters(): void {
  q.value = "";
  roleFilter.value = "";
  searchScope.value = "workspace";
  dateFrom.value = "";
  dateTo.value = "";
  amountMin.value = "";
  amountMax.value = "";
  sortBy.value = "invoice_date";
  sortDir.value = "desc";
  void runSearch();
}

function jumpDirectory(hit: WorkspaceSearchDirectoryHit): void {
  workspace.open({ kind: "directory", companyId: hit.company_id, dirKey: hit.dir_key });
  emit("navigateHome");
  emit("close");
}

function jumpProject(hit: WorkspaceSearchProjectHit): void {
  workspace.open({ kind: "project", companyId: hit.company_id, project: hit.project });
  emit("navigateHome");
  emit("close");
}

function jumpInvoice(hit: WorkspaceSearchInvoiceHit): void {
  const locateTerm = hit.invoice_number || hit.source_file || q.value.trim();
  workspace.locateInDirectory(hit.company_id, hit.dir_key, locateTerm);
  emit("navigateHome");
  emit("close");
}

watch([scope, companyId, searchScope, roleFilter, dateFrom, dateTo, sortBy, sortDir], () => void runSearch());

onMounted(async () => {
  if (!companies.list) void companies.load();
  await nextTick();
  inputRef.value?.focus();
  inputRef.value?.select();
  void runSearch();
});

onBeforeUnmount(() => {
  ++reqGen;
  clearTimeout(timer);
});
</script>

<template>
  <WsModal
    title="全局工作区搜索"
    subtitle="跨公司、跨目录只读检索已汇总发票、项目与目录（不扫描磁盘、不切换当前监控目录）。"
    :wide="true"
    @close="$emit('close')"
  >
    <div class="ws-gsearch">
      <div class="ws-gsearch__bar">
        <input
          ref="inputRef"
          v-model="q"
          type="search"
          class="ws-gsearch__input"
          aria-label="全局搜索关键字"
          placeholder="输入销售方 / 购买方 / 发票号 / 项目 / 金额 / 税率 / 文件名，空格分多词（回车立即搜索）"
          @input="scheduleSearch"
          @keydown.enter.prevent="runSearch"
        >
        <select v-model="scope" aria-label="检索公司范围">
          <option value="all">全部已登记公司</option>
          <option value="company" :disabled="!companies.companies.length">指定单家公司</option>
        </select>
        <select v-if="scope === 'company'" v-model="companyId" aria-label="选择公司">
          <option v-for="c in companies.companies" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <select v-model="searchScope" aria-label="匹配字段范围">
          <option value="workspace">全字段多词</option>
          <option value="party">购销方</option>
          <option value="buyer">仅购买方</option>
          <option value="invoice">销方 / 票号</option>
          <option value="filename">仅文件名</option>
        </select>
        <select v-model="roleFilter" aria-label="目录类型">
          <option value="">全部发票目录</option>
          <option value="cost_invoice_dir">成本发票（进项）</option>
          <option value="issued_invoice_dir">开具发票（销项）</option>
          <option value="expense_reimbursement_dir">费用报销</option>
        </select>
        <button type="button" class="ghost" :aria-expanded="advancedOpen" @click="advancedOpen = !advancedOpen">
          {{ advancedOpen ? "收起区间" : "日期 / 金额" }}
        </button>
        <button v-if="hasActiveFilters" type="button" class="ghost" @click="resetFilters">重置</button>
      </div>

      <div v-if="advancedOpen" class="ws-gsearch__adv">
        <label><span>开票起始</span><input v-model="dateFrom" type="date" aria-label="全局搜索开票起始日期"></label>
        <label><span>开票截止</span><input v-model="dateTo" type="date" aria-label="全局搜索开票截止日期"></label>
        <label><span>金额下限</span><input v-model="amountMin" type="text" inputmode="decimal" placeholder="如 100" aria-label="全局搜索金额下限" @input="scheduleSearch"></label>
        <label><span>金额上限</span><input v-model="amountMax" type="text" inputmode="decimal" placeholder="如 50000" aria-label="全局搜索金额上限" @input="scheduleSearch"></label>
        <label>
          <span>排序</span>
          <select v-model="sortBy" aria-label="全局搜索排序字段">
            <option value="invoice_date">开票时间</option>
            <option value="amount">开票金额</option>
          </select>
        </label>
        <label>
          <span>方向</span>
          <select v-model="sortDir" aria-label="全局搜索排序方向">
            <option value="desc">从高到低 / 最新优先</option>
            <option value="asc">从低到高 / 最早优先</option>
          </select>
        </label>
      </div>

      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <div v-if="payload" class="ws-gsearch__meta muted">
        <span>
          已检索 {{ payload.stats.companies_scanned }} 家公司、{{ payload.stats.directories_scanned }} 个已汇总目录（{{ payload.stats.invoices_scanned }} 条记录）
        </span>
        <span v-if="payload.stats.unbuilt_directories > 0">
          · 另有 {{ payload.stats.unbuilt_directories }} 个目录尚未读取数据，未参与检索
        </span>
        <span v-if="payload.truncated">· 结果超过单次上限，已展示前 {{ payload.items.length }} 条</span>
      </div>

      <p v-if="loading && !payload" class="muted" role="status" aria-busy="true">正在检索跨公司投影…</p>

      <template v-if="payload">
        <div v-if="payload.directories.length || payload.projects.length" class="ws-gsearch__entities">
          <div v-if="payload.directories.length" class="ws-gsearch__group">
            <h4>匹配目录（{{ payload.directories.length }}）</h4>
            <div class="ws-gsearch__chips">
              <button
                v-for="dir in payload.directories.slice(0, 12)"
                :key="`${dir.company_id}:${dir.dir_key}`"
                type="button"
                class="ws-gsearch__chip"
                @click="jumpDirectory(dir)"
              >
                <strong>{{ dir.dir_label }}</strong>
                <span class="muted">{{ dir.company_name }}</span>
                <span v-if="dir.monitored" class="tag">监控中</span>
              </button>
            </div>
          </div>
          <div v-if="payload.projects.length" class="ws-gsearch__group">
            <h4>匹配项目（{{ payload.projects.length }}）</h4>
            <div class="ws-gsearch__chips">
              <button
                v-for="proj in payload.projects.slice(0, 12)"
                :key="`${proj.company_id}:${proj.project}`"
                type="button"
                class="ws-gsearch__chip"
                @click="jumpProject(proj)"
              >
                <strong>{{ proj.project }}</strong>
                <span class="muted">{{ proj.company_name }}</span>
              </button>
            </div>
          </div>
        </div>

        <div class="ws-gsearch__table-wrap">
          <div class="ws-gsearch__section-head">
            <h4>匹配发票（{{ payload.total_matches }} 条<template v-if="loading">，更新中…</template>）</h4>
            <span class="muted">点击任意行打开对应目录并定位该发票</span>
          </div>
          <table v-if="payload.items.length" class="grid ws-gsearch__table" aria-label="全局发票搜索结果">
            <thead>
              <tr>
                <th>公司 / 目录</th>
                <th>销售方</th>
                <th>购买方</th>
                <th>发票号码</th>
                <th>项目</th>
                <th class="num">开票金额</th>
                <th>开票时间</th>
                <th>文件名</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(item, idx) in payload.items"
                :key="`${item.company_id}:${item.dir_key}:${item.invoice_key}:${idx}`"
                class="ws-gsearch__row"
                tabindex="0"
                @click="jumpInvoice(item)"
                @keydown.enter.prevent="jumpInvoice(item)"
              >
                <td>
                  <div class="ws-gsearch__loc">
                    <strong>{{ item.company_name }}</strong>
                    <span class="muted">{{ item.dir_label }}</span>
                    <span class="tag">{{ item.monitored ? "监控" : "只读" }}</span>
                  </div>
                </td>
                <td class="ws-gsearch__cell" :title="item.seller">{{ item.seller || "—" }}</td>
                <td class="ws-gsearch__cell" :title="item.buyer">{{ item.buyer || "—" }}</td>
                <td class="mono">{{ item.invoice_number || "—" }}</td>
                <td class="ws-gsearch__cell" :title="item.project || ''">{{ item.project || "—" }}</td>
                <td class="num mono">{{ money(item.amount) }}</td>
                <td class="mono nowrap">{{ item.invoice_date || "—" }}</td>
                <td class="ws-gsearch__cell path" :title="item.source_file">{{ item.source_file || "—" }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else-if="!loading" class="muted ws-gsearch__empty">没有匹配当前条件的发票记录。</p>
        </div>
      </template>
    </div>
  </WsModal>
</template>

<style scoped>
.ws-gsearch { display: grid; gap: 12px; }
.ws-gsearch__bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ws-gsearch__input { flex: 1 1 280px; min-width: 220px; }
.ws-gsearch__adv {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px 12px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
}
.ws-gsearch__adv label { display: grid; gap: 4px; font-size: 12px; }
.ws-gsearch__meta { font-size: 12px; display: flex; flex-wrap: wrap; gap: 4px; }
.ws-gsearch__entities { display: grid; gap: 10px; }
.ws-gsearch__group h4, .ws-gsearch__section-head h4 { margin: 0 0 6px; font-size: 13px; }
.ws-gsearch__chips { display: flex; flex-wrap: wrap; gap: 6px; }
.ws-gsearch__chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px;
  background: var(--surface); color: var(--text); font-size: 12px; cursor: pointer;
}
.ws-gsearch__chip:hover { border-color: var(--accent); }
.ws-gsearch__section-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.ws-gsearch__table-wrap { max-height: 46vh; overflow: auto; }
.ws-gsearch__row { cursor: pointer; }
.ws-gsearch__row:hover, .ws-gsearch__row:focus-visible { background: var(--hover, rgba(0, 0, 0, 0.04)); outline: none; }
.ws-gsearch__loc { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; font-size: 12px; }
.ws-gsearch__cell { max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ws-gsearch__empty { padding: 18px 0; text-align: center; }
</style>
