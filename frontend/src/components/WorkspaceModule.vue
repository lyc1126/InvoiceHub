<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { ModuleId } from "../modules";
import { useCompaniesStore } from "../stores/companies";
import { useModulesStore } from "../stores/modules";
import ClassicModuleView from "./ClassicModuleView.vue";
import CompanyVouchers from "./CompanyVouchers.vue";
import CompanyTax from "./CompanyTax.vue";
import CompanyPayroll from "./CompanyPayroll.vue";
import CompanyCompare from "./CompanyCompare.vue";
import InvoiceTagsEditor from "./InvoiceTagsEditor.vue";
import WatchSwitchConfirm from "./WatchSwitchConfirm.vue";
import WorkspaceIcon from "./WorkspaceIcon.vue";
import MonthPicker from "./MonthPicker.vue";

const props = defineProps<{ module: ModuleId; path: string; label: string; active: boolean; recovery: boolean }>();
const emit = defineEmits<{ navigate: [path: string]; appearance: []; stateChanged: [] }>();
const modules = useModulesStore();
const companies = useCompaniesStore();
const selection = computed(() => modules.selections[props.module]);
const company = computed(() => companies.companies.find(item => item.id === selection.value?.companyId));
const subdir = computed(() => company.value?.subdirs.find(item => item.key === selection.value?.dirKey));
const section = ref("voucher");
const opened = ref(new Set(["voucher"]));
const visitedCompanies = ref(new Set<string>());
watch(() => company.value?.id, id => { if (id) visitedCompanies.value.add(id); }, { immediate: true });
const switching = ref(false);
const bookTabs = [{ id: "voucher", label: "凭证" }, { id: "stock", label: "库存" }, { id: "salary", label: "工资社保" }, { id: "tax", label: "税费" }, { id: "mapping", label: "映射规则" }, { id: "setup", label: "账套设置" }];
function selectSection(id: string): void { section.value = id; opened.value.add(id); }
// Legacy modules still consume the single active target. A different company must
// never relabel that data; show a deliberate handoff until its API is company-aware.
const activeSource = computed(() => !!company.value?.monitored && (!subdir.value || company.value.monitored_subdir_key === subdir.value.key));
const classicVisible = computed(() => props.module === "settings" || (props.module !== "bookkeeping" && activeSource.value) || (props.module === "bookkeeping" && !!company.value && ["mapping", "setup"].includes(section.value)));
const book = computed(() => company.value ? modules.book[company.value.id] : undefined);
const presentDirs = computed(() => company.value?.subdirs.filter(item => item.status === "present").length ?? 0);
const switchPath = computed(() => subdir.value?.path ?? company.value?.subdirs.find(item => item.key === "cost_invoice_dir")?.path ?? "");
</script>

<template>
  <section class="workspace-module" :class="{ 'workspace-module--settings': module === 'settings' }" :aria-label="`${label}工作区`">
    <header v-if="company && module !== 'settings'" class="module-context" :class="{ 'module-context--tools': module === 'bookkeeping' }">
      <div>
        <p class="crumb">{{ company.name }} › {{ label }}</p>
        <h2>{{ label }}<template v-if="module === 'bookkeeping' && book?.month"> · {{ book.month.slice(0, 4) }} 年 {{ Number(book.month.slice(5)) }} 月</template></h2>
        <p class="path">{{ subdir?.path ?? company.root_path }}<template v-if="selection?.project"> · {{ selection.project }}（公司范围）</template></p>
      </div>
      <!-- Prototype bkView head: info, period picker (months that have drafts), primary export. -->
      <div v-if="module === 'bookkeeping' && book" class="module-context__tools">
        <span class="info" tabindex="0" title="所属期决定凭证进哪个月的草稿；记账日期必须落在所属期内。导出只导出审核通过的凭证。">i</span>
        <template v-if="book.months.length">
          <MonthPicker v-model="book.month" label="做账所属期" :marked="book.months" :only="true" />
          <button v-if="book.month" type="button" class="ghost" @click="book.month = ''">全部月份</button>
        </template>
        <button type="button" class="primary" :disabled="!book.exportable" :title="book.exportable ? '' : '没有审核通过的凭证，或有未保存的改动'" @click="book.exportTick += 1">导出凭证（{{ book.approved }}）</button>
      </div>
    </header>
    <template v-if="module === 'settings'">
      <!-- Prototype settings: global header, then the tag table, then the unchanged classic
           settings pages. The whole column scrolls; the frame keeps a full-viewport height. -->
      <header class="module-context"><h2>设置</h2><p>全局设置，不随公司切换</p></header>
      <div class="module-company-content"><InvoiceTagsEditor /></div>
    </template>
    <div v-else-if="!company" class="module-empty">
      <WorkspaceIcon :name="module === 'bookkeeping' ? 'book' : module === 'costs' ? 'costs' : 'folder'" />
      <h2>{{ label }}</h2><p>从左侧选择{{ module === 'bookkeeping' ? '一家公司开始做账' : '公司或目录' }}。每个模块分别记住自己选中的对象和页面位置，去别的模块再回来不会丢。</p>
    </div>
    <div v-if="module === 'bookkeeping' && company" class="module-company-content bookkeeping-workspace" :class="{ 'bookkeeping-workspace--classic': classicVisible }">
      <!-- Only step 1 has a company-level fact here (subdir presence); later steps stay neutral
           rather than guessing draft state that CompanyVouchers owns. -->
      <div class="bookkeeping-flow" aria-label="做账流程">
        <div :class="presentDirs === company.subdirs.length ? 'done' : 'warn'"><b><i>{{ presentDirs === company.subdirs.length ? "✓" : "!" }}</i>资料齐全</b><small>{{ presentDirs }}/{{ company.subdirs.length }} 个文件夹有资料</small></div>
        <div v-for="(step, index) in ['生成草稿', '人工审核', '导出凭证', '导入记账软件 / 读回']" :key="step"><b><i>{{ index + 2 }}</i>{{ step }}</b><small>{{ ['生成后逐张核对', '由你确认', '只导出审核通过的', '在记账软件导入后读回核对'][index] }}</small></div>
      </div>
      <div class="tabs" role="tablist" aria-label="做账内容"><button v-for="item in bookTabs" :key="item.id" type="button" role="tab" :aria-selected="section === item.id" @click="selectSection(item.id)">{{ item.label }}</button></div>
      <!-- Company-keyed caches prevent switching the sidebar from retaining another
           company's draft UI. Returning to a company restores its existing editors. -->
      <template v-for="item in companies.companies" :key="`${item.id}:${modules.refresh.bookkeeping ?? 0}`">
        <div v-if="visitedCompanies.has(item.id)" v-show="item.id === company.id">
          <CompanyVouchers v-if="opened.has('voucher')" v-show="section === 'voucher'" :company="item" layout="split" />
          <CompanyCompare v-if="opened.has('stock')" v-show="section === 'stock'" :company="item" relation="inventory" :active="active && item.id === company.id && section === 'stock'" />
          <CompanyPayroll v-if="opened.has('salary')" v-show="section === 'salary'" :company="item" />
        </div>
      </template>
      <CompanyTax v-if="section === 'tax'" :company="company" :start="book?.month" :end="book?.month" />
      <p v-if="['mapping', 'setup'].includes(section)" class="overview-notice">下方沿用现有账套设置和映射功能，实际作用目录以下方设置为准。</p>
    </div>
    <div v-if="company && module !== 'settings' && module !== 'bookkeeping' && !activeSource" class="module-empty">
      <WorkspaceIcon name="folder" /><h2>{{ company.name }} · {{ label }}</h2><p>当前模块仍读取监控目录。所选公司或目录尚未接入此模块，不能展示其它目录的结果。</p>
      <button v-if="switchPath" type="button" @click="switching = true">设为监控目录后使用</button>
      <WatchSwitchConfirm v-if="switching" :path="switchPath" @done="switching = false" @cancel="switching = false" />
    </div>
    <ClassicModuleView v-show="classicVisible" :module="module" :path="path" :label="label" :active="active && classicVisible" :recovery="recovery" @navigate="emit('navigate', $event)" @appearance="emit('appearance')" @state-changed="emit('stateChanged')" />
  </section>
</template>
