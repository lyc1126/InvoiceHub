<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company } from "../api/types";
import { errorText, money } from "../format";
import { companySourceKey } from "../stores/companies";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

interface SalaryRow { name: string; id_number: string; gross: string; deductions: string; net: string; social: string | null; fund: string | null; tax: string | null; other: string | null; expense_path: string }
interface SalaryEntry { month: string; candidate_id: string; source: string; rows: SalaryRow[]; headcount: number; totals: Record<string, string | null>; needs_expense_path: boolean; source_current?: boolean }
interface SalaryPayload { candidates: SalaryEntry[]; confirmed: Record<string, SalaryEntry>; files: { file: string; status: string; message: string }[]; source_revision: string; tax_revision: string | null; tax_file: boolean; current_month: string }
const props = defineProps<{ company: Company; month?: string; taxRevision?: string | null }>();
const emit = defineEmits<{ saved: [] }>();
const data = ref<SalaryPayload | null>(null);
const error = ref("");
const loading = ref(false);
const saving = ref(false);
const unknown = ref(false);
const reveal = ref(false);
const selected = ref("");
const page = ref(0);
const confirmation = ref<SalaryEntry | null>(null);
const expensePath = ref("");
const base = computed(() => `/api/v1/companies/${encodeURIComponent(props.company.id)}/salary`);
const current = computed(() => data.value?.candidates.find(item => item.candidate_id === selected.value));
const visibleRows = computed(() => current.value?.rows.slice(page.value * 50, (page.value + 1) * 50) ?? []);
let generation = 0;
let disposed = false;

async function load(): Promise<void> {
  const mine = ++generation;
  loading.value = true;
  try {
    const result = await request<SalaryPayload>(`${base.value}${reveal.value ? "?reveal=true" : ""}`, { timeoutMs: 60_000 });
    if (disposed || mine !== generation) return;
    data.value = result;
    if (!result.candidates.some(item => item.candidate_id === selected.value)) {
      selected.value = (result.candidates.find(item => item.month === props.month) ?? result.candidates[0])?.candidate_id ?? "";
      page.value = 0;
    }
    unknown.value = false;
    error.value = "";
  } catch (cause) { if (!disposed && mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) loading.value = false; }
}

function openConfirm(): void {
  if (!current.value || loading.value || saving.value || unknown.value) return;
  confirmation.value = current.value;
  expensePath.value = "";
}

async function save(entry: SalaryEntry, remove = false): Promise<void> {
  if (!data.value || saving.value || loading.value || unknown.value) return;
  const mine = generation;
  const url = base.value;
  const month = entry.month;
  const body = { revision: data.value.tax_revision, month, ...(remove ? { remove: true } : {
    source_revision: data.value.source_revision, candidate_id: entry.candidate_id, expense_path: expensePath.value,
  }) };
  saving.value = true;
  error.value = "";
  try {
    await request(url, { method: "PUT", body });
    if (disposed || mine !== generation) return;
    confirmation.value = null;
    toast(remove ? `已取消 ${month} 工资确认；重新生成草稿后生效。` : `已确认 ${month} 工资；重新生成草稿后计提。`);
    emit("saved");
    await load();
  } catch (cause) {
    if (disposed || mine !== generation) return;
    if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
      confirmation.value = null;
      if (cause.status === 409) await load();
      error.value = errorText(cause);
    } else {
      // A lost write response cannot authorize another confirmation. A successful
      // read-back of the full record is required before any further salary write.
      unknown.value = true;
      confirmation.value = null;
      error.value = "工资保存结果待核对，请读取确认结果；不会自动重发。";
    }
  } finally { saving.value = false; }
}

watch(selected, () => { page.value = 0; });
watch(reveal, () => {
  // Hide previously revealed personnel immediately, even if the masked reload fails.
  data.value = null;
  confirmation.value = null;
  void load();
});
watch(() => props.taxRevision, (value, previous) => { if (previous !== undefined && value !== previous && !saving.value) void load(); });
watch(() => companySourceKey(props.company, ["payroll_social_dir"]), () => {
  generation += 1;
  data.value = null;
  confirmation.value = null;
  unknown.value = false;
  reveal.value = false;
  void load();
}, { immediate: true });
onBeforeUnmount(() => { disposed = true; generation += 1; });
</script>

<template>
  <section class="panel" aria-label="工资表与工资计提">
    <header class="voucher__head"><h3>工资表与工资计提</h3><button type="button" :disabled="loading || saving" :aria-busy="loading" @click="load">{{ loading ? '读取中…' : unknown ? '读取确认结果' : '重新读取工资表' }}</button></header>
    <p class="overview-notice">读取工资社保目录内的 Excel 工资表。核对所属期、应发 − 扣款 = 实发后，明确成本费用科目再确认。只计提应发工资，扣款仅作核对，不生成付款或重复扣记社保。</p>
    <details class="muted"><summary>支持的表头与格式</summary><p>必需：姓名、工资所属期（或表内唯一年月标题）、应发工资、实发工资，以及扣款合计；也可完整提供代扣社保、代扣公积金、代扣个税、其他扣款四列。零请填 0，空白保留未知。可选：证件号码、费用科目路径。支持 .xlsx / .xlsm 仅值表；公式请在原表计算核对后另存为仅值表。相同月份有多份文件时须逐份核对并明确选用，不自动相加。</p></details>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <template v-if="data">
      <p v-if="!data.tax_file" class="muted">请先生成一次凭证草稿，建立申报数据模板后再确认工资。</p>
      <ul v-if="data.files.some(item => item.status === 'error')" class="warnings"><li v-for="file in data.files.filter(item => item.status === 'error')" :key="file.file">{{ file.file }}：{{ file.message }}</li></ul>
      <div v-if="data.candidates.length" class="toolbar">
        <label class="field">工资来源<select v-model="selected" aria-label="工资来源" :disabled="saving || loading || unknown"><option v-for="entry in data.candidates" :key="entry.candidate_id" :value="entry.candidate_id">{{ entry.month }} · {{ entry.source }} · {{ entry.headcount }} 人</option></select></label>
        <label><input v-model="reveal" type="checkbox" :disabled="loading || saving"> 显示工资表完整姓名与证件号</label>
      </div>
      <article v-if="current" :aria-label="`${current.month} 工资表`">
        <p><b>{{ current.month }}</b> · {{ current.headcount }} 人 · 应发 {{ money(current.totals.gross) }} · 扣款 {{ money(current.totals.deductions) }} · 实发 {{ money(current.totals.net) }} <span class="tag pill-ok">逐行核对成立</span></p>
        <div class="overview-table-wrap"><table class="grid">
          <thead><tr><th>姓名</th><th>证件号码</th><th class="num">应发</th><th class="num">代扣社保</th><th class="num">代扣公积金</th><th class="num">代扣个税</th><th class="num">其他扣款</th><th class="num">扣款合计</th><th class="num">实发</th><th>费用科目路径</th></tr></thead>
          <tbody><tr v-for="(row, index) in visibleRows" :key="index"><td>{{ row.name }}</td><td>{{ row.id_number || '—' }}</td><td v-for="field in ['gross', 'social', 'fund', 'tax', 'other', 'deductions', 'net'] as const" :key="field" class="num">{{ row[field] === null ? '—' : money(row[field]) }}</td><td>{{ row.expense_path || '确认时指定' }}</td></tr></tbody>
        </table></div>
        <div class="toolbar"><button type="button" :disabled="page === 0" @click="page--">上一页</button><span>{{ page + 1 }} / {{ Math.max(1, Math.ceil(current.rows.length / 50)) }}</span><button type="button" :disabled="(page + 1) * 50 >= current.rows.length" @click="page++">下一页</button>
          <button type="button" class="primary" :disabled="saving || loading || unknown || !data.tax_file || current.month > data.current_month" @click="openConfirm">{{ data.confirmed[current.month] ? '重新确认工资…' : '确认工资计提…' }}</button>
        </div>
      </article>
      <p v-else-if="!loading" class="muted">没有可读取的工资表；未生成工资计提。</p>
      <section v-if="Object.keys(data.confirmed).length" aria-label="已确认工资">
        <h4>已确认工资</h4><div class="overview-table-wrap"><table class="grid"><thead><tr><th>月份</th><th>来源</th><th class="num">应发</th><th>原表核验</th><th>操作</th></tr></thead><tbody>
          <tr v-for="(entry, savedMonth) in data.confirmed" :key="savedMonth"><td>{{ savedMonth }}</td><td>{{ entry.source }}</td><td class="num">{{ money(entry.totals.gross) }}</td><td :class="{ 'check--failed': !entry.source_current }">{{ entry.source_current ? '与确认时一致' : '原表已变更或不可读，须重新确认' }}</td><td><button type="button" :disabled="loading || saving || unknown" @click="save({ ...entry, month: String(savedMonth) }, true)">取消工资确认</button></td></tr>
        </tbody></table></div>
      </section>
    </template>
    <WsModal v-if="confirmation" title="确认工资计提" @close="!saving && (confirmation = null)">
      <p>{{ confirmation.month }} · {{ confirmation.source }} · {{ confirmation.headcount }} 人，应发 {{ money(confirmation.totals.gross) }}。</p>
      <label v-if="confirmation.needs_expense_path" class="field">未指定行的成本费用科目路径<input v-model="expensePath" aria-label="工资计提费用科目路径" placeholder="如 管理费用/管理人员职工薪酬" :disabled="saving"></label>
      <p class="muted">确认后写入申报数据.json；已有该月工资确认会替换。重新生成草稿后，按明确的科目路径借记成本费用、贷记应付职工工资。缺科目会列入待补，仍需人工审核。</p>
      <div class="actions"><button type="button" class="primary" :disabled="saving || (confirmation.needs_expense_path && !expensePath.trim())" :aria-busy="saving" @click="save(confirmation)">{{ saving ? '保存中…' : '确认写入工资明细' }}</button><button type="button" :disabled="saving" @click="confirmation = null">取消</button></div>
    </WsModal>
  </section>
</template>
