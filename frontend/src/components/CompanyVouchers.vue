<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company } from "../api/types";
import { errorText, money } from "../format";

// Voucher drafts (WS-05 stage 1): the CLI's review workbook in 做账草稿/, edited cell by cell.
// The page only shows a live debit/credit total while typing; the backend re-checks every
// voucher with the export rules on save and refuses to approve one that fails.
interface DraftLine {
  row: number; summary: string; code: string; name: string; debit: string | null; credit: string | null;
  supplier: string; qty: string | null; unit: string; todo: string; confidence: string; basis: string;
}
interface DraftVoucher {
  month: string; number: string; date: string; approval: string; debit_total: string; credit_total: string;
  errors: string[]; warnings: string[]; lines: DraftLine[];
}
interface DraftSheet { name: string; columns: (string | number)[]; rows: (string | number)[][]; truncated: boolean }
interface DraftPayload {
  name: string; revision: string; books_error: string; vouchers: DraftVoucher[]; approved: number; blocked: number;
  sheets?: DraftSheet[]; current_month?: string;
}
interface Moved { from: { month: string; number: string }; to: { month: string; number: string } }
interface ExportResult {
  files: string[]; exported: number; skipped: number; blocked_months: string[]; duplicates: string[]; learned: number;
  errors: { voucher: string; errors: string[] }[]; warnings: { voucher: string; warnings: string[] }[];
}
type Editable = "summary" | "code" | "debit" | "credit" | "supplier";

const props = defineProps<{ company: Company }>();
const base = computed(() => `/api/v1/companies/${encodeURIComponent(props.company.id)}/voucher-drafts`);
const files = ref<{ name: string }[] | null>(null);
const selectedFile = ref("");
const draft = ref<DraftPayload | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");
const refused = ref<Record<string, string[]>>({});
const month = ref("");
const onlyProblems = ref(false);
// Unsaved edits: row → field → text, and voucher key → approval.
const edits = reactive<Record<number, Partial<Record<Editable, string>>>>({});
const approvals = reactive<Record<string, string>>({});
// 所属期 / 记账日期 (stage 2), by voucher key. The backend renumbers a voucher moved to another month.
const periods = reactive<Record<string, { month: string; date: string }>>({});
// Export (stage 2): the same jierui.export the CLI runs, on an explicit confirm, for the saved file.
const exportOpen = ref(false);
const exporting = ref(false);
const preparer = ref("");
// v-model on a number input yields a number once typed, "" when cleared.
const afterNumbers = reactive<Record<string, string | number>>({});
const exportResult = ref<ExportResult | null>(null);
const approvedByMonth = computed(() => {
  const counts: Record<string, number> = {};
  for (const voucher of draft.value?.vouchers ?? []) if (voucher.approval === "通过") counts[voucher.month] = (counts[voucher.month] ?? 0) + 1;
  return Object.entries(counts).sort(([a], [b]) => a.localeCompare(b));
});
const numberFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 });
const cellText = (value: string | number) => (typeof value === "number" ? numberFormat.format(value) : value);

const keyOf = (voucher: DraftVoucher) => `${voucher.month}#${voucher.number}`;
const months = computed(() => [...new Set((draft.value?.vouchers ?? []).map((item) => item.month))]);
const shown = computed(() =>
  (draft.value?.vouchers ?? []).filter((item) => (!month.value || item.month === month.value) && (!onlyProblems.value || item.errors.length || refused.value[keyOf(item)])),
);
const dirtyCount = computed(() => {
  const keys = new Set([...Object.keys(approvals), ...Object.keys(periods)]);
  for (const voucher of draft.value?.vouchers ?? []) if (voucher.lines.some((line) => edits[line.row])) keys.add(keyOf(voucher));
  return keys.size;
});

function value(line: DraftLine, field: Editable): string {
  return edits[line.row]?.[field] ?? line[field] ?? "";
}

function edit(line: DraftLine, field: Editable, text: string): void {
  edits[line.row] = { ...edits[line.row], [field]: text };
}

function cents(text: string): number | null {
  const cleaned = text.replace(/,/g, "").trim();
  if (!cleaned) return 0;
  return /^-?\d+(\.\d{1,2})?$/.test(cleaned) ? Math.round(Number(cleaned) * 100) : null;
}

// Display only: the live totals while typing. The backend's check on save is what counts.
function totals(voucher: DraftVoucher): { debit: string; credit: string; balanced: boolean; readable: boolean } {
  let debit = 0;
  let credit = 0;
  let readable = true;
  for (const line of voucher.lines) {
    const d = cents(value(line, "debit"));
    const c = cents(value(line, "credit"));
    if (d === null || c === null) readable = false;
    debit += d ?? 0;
    credit += c ?? 0;
  }
  const show = (amount: number) => money((amount / 100).toFixed(2));
  return { debit: show(debit), credit: show(credit), balanced: readable && debit === credit, readable };
}

function approvalOf(voucher: DraftVoucher): string {
  return approvals[keyOf(voucher)] ?? voucher.approval;
}

function resetEdits(): void {
  for (const key of Object.keys(edits)) delete edits[Number(key)];
  for (const key of Object.keys(approvals)) delete approvals[key];
  for (const key of Object.keys(periods)) delete periods[key];
}

function periodOf(voucher: DraftVoucher): { month: string; date: string } {
  return periods[keyOf(voucher)] ?? { month: voucher.month, date: voucher.date };
}

function lastDay(month: string): string {
  const [year, number] = month.split("-").map(Number);
  return `${month}-${String(new Date(year!, number!, 0).getDate()).padStart(2, "0")}`;
}

function setPeriod(voucher: DraftVoucher, field: "month" | "date", value: string): void {
  if (!value) return;
  const next = { ...periodOf(voucher), [field]: value };
  // A new month moves the date to its last day (the draft's month-end convention) unless it already fits.
  if (field === "month" && !next.date.startsWith(`${value}-`)) next.date = lastDay(value);
  if (next.month === voucher.month && next.date === voucher.date) delete periods[keyOf(voucher)];
  else periods[keyOf(voucher)] = next;
}

async function loadFiles(): Promise<void> {
  error.value = "";
  try {
    files.value = (await request<{ drafts: { name: string }[] }>(base.value)).drafts;
    if (!files.value.some((item) => item.name === selectedFile.value)) selectedFile.value = files.value.at(-1)?.name ?? "";
  } catch (cause) {
    error.value = errorText(cause);
  }
}

async function loadDraft(): Promise<void> {
  if (!selectedFile.value) {
    draft.value = null;
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    draft.value = await request<DraftPayload>(`${base.value}/${encodeURIComponent(selectedFile.value)}`);
    resetEdits();
    refused.value = {};
    if (month.value && !months.value.includes(month.value)) month.value = "";
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    loading.value = false;
  }
}

async function save(): Promise<void> {
  if (!draft.value || !dirtyCount.value) return;
  saving.value = true;
  error.value = "";
  notice.value = "";
  const changes = draft.value.vouchers
    .map((voucher) => {
      const lines = voucher.lines.filter((line) => edits[line.row]).map((line) => ({ row: line.row, ...edits[line.row] }));
      const approval = approvals[keyOf(voucher)];
      const period = periods[keyOf(voucher)];
      if (!lines.length && approval === undefined && !period) return null;
      return {
        month: voucher.month, number: voucher.number, ...(approval !== undefined ? { approval } : {}),
        ...(period ? { move_month: period.month, date: period.date } : {}), lines,
      };
    })
    .filter((item) => item !== null);
  try {
    const saved = await request<DraftPayload & { saved_rows: number; saved_approvals: number; moved: Moved[] }>(
      `${base.value}/${encodeURIComponent(draft.value.name)}`,
      { method: "PUT", body: { revision: draft.value.revision, vouchers: changes } },
    );
    draft.value = saved;
    resetEdits();
    refused.value = {};
    const movedAll = saved.moved ?? [];
    const moved = movedAll.filter((item) => item.from.month !== item.to.month || item.from.number !== item.to.number)
      .map((item) => `${item.from.month} 第 ${item.from.number} 号 → ${item.to.month} 第 ${item.to.number} 号`);
    notice.value = `已保存：改动 ${saved.saved_rows} 行、审核状态 ${saved.saved_approvals} 张${movedAll.length ? `、所属期 / 日期 ${movedAll.length} 张` : ""}。`
      + (moved.length ? `移动后重新编号：${moved.join("；")}。` : "");
  } catch (cause) {
    if (cause instanceof ApiError && cause.code === "VOUCHER_DRAFT_CONFLICT") {
      await loadDraft();
      error.value = "审核表已在别处修改（或重新生成），已刷新，请重新编辑。";
    } else if (cause instanceof ApiError && cause.code === "VOUCHER_DRAFT_NOT_APPROVABLE") {
      // Nothing was written; the edits stay on the page next to the reasons.
      refused.value = Object.fromEntries((cause.details as { month: string; number: string; errors: string[] }[]).map((item) => [`${item.month}#${item.number}`, item.errors]));
      error.value = "有凭证未通过校验，不能审核通过；未保存任何改动。";
    } else {
      error.value = errorText(cause);
    }
  } finally {
    saving.value = false;
  }
}

async function runExport(): Promise<void> {
  if (!draft.value) return;
  exporting.value = true;
  error.value = "";
  exportResult.value = null;
  const after = Object.fromEntries(Object.entries(afterNumbers).filter(([, value]) => String(value ?? "").trim() !== "").map(([month, value]) => [month, Number(value)]));
  try {
    exportResult.value = await request<ExportResult>(`${base.value}/${encodeURIComponent(draft.value.name)}/export`, {
      method: "POST", body: { revision: draft.value.revision, preparer: preparer.value, after, confirm: true }, timeoutMs: 60_000,
    });
    exportOpen.value = false;
  } catch (cause) {
    if (cause instanceof ApiError && cause.code === "VOUCHER_DRAFT_CONFLICT") {
      await loadDraft();
      error.value = "审核表已在别处修改（或重新生成），已刷新，请重新核对后再导出。";
    } else {
      error.value = errorText(cause);
    }
  } finally {
    exporting.value = false;
  }
}

watch(selectedFile, () => void loadDraft());
watch(
  () => props.company.id,
  () => {
    files.value = null;
    selectedFile.value = "";
    draft.value = null;
    void loadFiles();
  },
  { immediate: true },
);
</script>

<template>
  <section aria-label="凭证草稿">
    <div class="toolbar">
      <select v-model="selectedFile" aria-label="审核表" :disabled="!files?.length">
        <option v-for="file in files ?? []" :key="file.name" :value="file.name">{{ file.name }}</option>
      </select>
      <select v-if="months.length > 1" v-model="month" aria-label="月份">
        <option value="">全部月份</option>
        <option v-for="item in months" :key="item" :value="item">{{ item }}</option>
      </select>
      <label class="nowrap"><input v-model="onlyProblems" type="checkbox"> 只看有问题的</label>
      <button type="button" :disabled="loading" @click="loadFiles().then(loadDraft)">重新读取</button>
      <button type="button" class="primary" :disabled="saving || !dirtyCount" :aria-busy="saving" @click="save">
        {{ saving ? "保存中…" : `保存（${dirtyCount} 张）` }}
      </button>
      <button
        type="button"
        :disabled="!draft || !draft.approved || dirtyCount > 0 || exporting"
        :title="dirtyCount ? '先保存改动再导出' : !draft?.approved ? '还没有审核通过的凭证' : ''"
        @click="exportOpen = !exportOpen; exportResult = null"
      >导出已审核…</button>
    </div>
    <section v-if="exportOpen && draft" class="panel" role="group" aria-label="导出已审核凭证">
      <p>
        将审核为“通过”的 {{ draft.approved }} 张凭证导出为账套导入文件，写到公司资料夹 做账草稿/，由会计人员在账套中手工导入（不连接账套）。
        某月有凭证校验不通过时该月整月不导出；已导出过的凭证会跳过，不会重复导出。
      </p>
      <table class="grid">
        <thead><tr><th>月份</th><th class="num">通过</th><th>账套该月已用到的凭证号（没有可空）</th></tr></thead>
        <tbody>
          <tr v-for="[month, count] in approvedByMonth" :key="month">
            <td>{{ month }}</td>
            <td class="num">{{ count }}</td>
            <td><input v-model="afterNumbers[month]" type="number" min="0" max="999" inputmode="numeric" :aria-label="`${month} 账套已用到的凭证号`"></td>
          </tr>
        </tbody>
      </table>
      <div class="toolbar">
        <label class="nowrap">制单人 <input v-model="preparer" maxlength="20" aria-label="制单人" placeholder="与账套里的制单人一致"></label>
        <button type="button" class="primary" :disabled="exporting || !preparer.trim()" :aria-busy="exporting" @click="runExport">{{ exporting ? "导出中…" : "确认导出" }}</button>
        <button type="button" @click="exportOpen = false">取消</button>
      </div>
    </section>
    <section v-if="exportResult" class="panel" role="status" aria-label="导出结果">
      <p :class="{ 'check--failed': exportResult.blocked_months.length }">
        已导出 {{ exportResult.exported }} 张，未导出 {{ exportResult.skipped }} 张<template v-if="exportResult.learned">；记住科目习惯 {{ exportResult.learned }} 条</template>。
      </p>
      <ul v-if="exportResult.files.length" class="warnings warnings--compact">
        <li v-for="file in exportResult.files" :key="file">做账草稿/{{ file }}</li>
      </ul>
      <p v-for="month in exportResult.blocked_months" :key="month" class="check--failed">{{ month }} 整月未导出：该月有凭证未通过校验，修正后整月一起导出，避免只导入半个月。</p>
      <ul v-if="exportResult.errors.length" class="warnings warnings--compact">
        <li v-for="item in exportResult.errors" :key="item.voucher" class="check--failed">{{ item.voucher }}：{{ item.errors.join("；") }}</li>
      </ul>
      <ul v-if="exportResult.duplicates.length" class="warnings warnings--compact">
        <li v-for="item in exportResult.duplicates" :key="item">已导出过，跳过：{{ item }}</li>
      </ul>
      <ul v-if="exportResult.warnings.length" class="warnings warnings--compact">
        <li v-for="item in exportResult.warnings" :key="item.voucher">提醒 {{ item.voucher }}：{{ item.warnings.join("；") }}</li>
      </ul>
    </section>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <p v-if="files && !files.length" class="muted">
      公司资料夹 做账草稿/ 里还没有凭证审核表。先用 <code>python -m invoice_hub.bank.voucher_cli draft</code> 生成，再在这里审核和修改。
    </p>
    <template v-if="draft">
      <p class="banner banner--note">
        参考凭证需人工审核。共 {{ draft.vouchers.length }} 张，已通过 {{ draft.approved }} 张，有问题 {{ draft.blocked }} 张。
        改动过的凭证（含所属期、记账日期）要重新审核；借贷不平、科目不可用或记账日期不在所属期内时不能审核通过。保存只写这份审核表，导出只写 做账草稿/，都不写 凭证/、不连接账套。
      </p>
      <p v-if="draft.books_error" class="banner banner--error" role="alert">{{ draft.books_error }}</p>
      <details v-for="sheet in draft.sheets ?? []" :key="sheet.name" class="checks">
        <summary><strong>{{ sheet.name }}</strong> <span class="muted">{{ sheet.rows.length }} 行{{ sheet.truncated ? "（只显示前 2000 行）" : "" }} · 由生成命令写入，只读</span></summary>
        <table class="grid" :aria-label="sheet.name">
          <thead><tr><th v-for="(column, index) in sheet.columns" :key="index">{{ column }}</th></tr></thead>
          <tbody>
            <tr v-for="(row, index) in sheet.rows" :key="index">
              <td v-for="(value, column) in row" :key="column" :class="{ num: typeof value === 'number' }">{{ cellText(value) }}</td>
            </tr>
          </tbody>
        </table>
      </details>

      <article
        v-for="voucher in shown"
        :key="keyOf(voucher)"
        class="voucher"
        :class="{ 'voucher--failed': voucher.errors.length || refused[keyOf(voucher)] }"
        :aria-label="`${voucher.month} 第 ${voucher.number} 号凭证`"
      >
        <header class="voucher__head">
          <strong>{{ voucher.month }} · 记-{{ voucher.number }}</strong>
          <label class="nowrap">所属期
            <input
              type="month"
              :value="periodOf(voucher).month"
              :max="draft.current_month"
              :aria-label="`${voucher.month} 第 ${voucher.number} 号凭证所属期`"
              @change="setPeriod(voucher, 'month', ($event.target as HTMLInputElement).value)"
            >
          </label>
          <label class="nowrap">记账日期
            <input
              type="date"
              :value="periodOf(voucher).date"
              :min="`${periodOf(voucher).month}-01`"
              :max="lastDay(periodOf(voucher).month)"
              :aria-label="`${voucher.month} 第 ${voucher.number} 号凭证记账日期`"
              @change="setPeriod(voucher, 'date', ($event.target as HTMLInputElement).value)"
            >
          </label>
          <span class="voucher__totals" :class="totals(voucher).balanced ? 'muted' : 'check--failed'">
            借 {{ totals(voucher).debit }} · 贷 {{ totals(voucher).credit }}{{ totals(voucher).readable ? (totals(voucher).balanced ? "" : " · 不平") : " · 金额无法识别" }}
          </span>
          <select
            :value="approvalOf(voucher)"
            :aria-label="`${voucher.month} 第 ${voucher.number} 号凭证审核`"
            @change="approvals[keyOf(voucher)] = ($event.target as HTMLSelectElement).value"
          >
            <option value="">待审核</option>
            <option value="通过">通过</option>
            <option value="不导入">不导入</option>
          </select>
        </header>
        <p v-if="periods[keyOf(voucher)] && periods[keyOf(voucher)]!.month !== voucher.month" class="muted voucher__stale">
          保存后移到 {{ periods[keyOf(voucher)]!.month }}，并接在该月已有凭证号之后重新编号；需要重新审核。
        </p>
        <p v-if="!refused[keyOf(voucher)] && voucher.errors.length && voucher.lines.some((line) => edits[line.row])" class="muted voucher__stale">
          下面是上次保存时的校验结果，保存后重新校验。
        </p>
        <ul v-if="refused[keyOf(voucher)] || voucher.errors.length" class="warnings warnings--compact">
          <li v-for="text in refused[keyOf(voucher)] ?? voucher.errors" :key="text" class="check--failed">{{ text }}</li>
        </ul>
        <ul v-if="voucher.warnings.length" class="warnings warnings--compact">
          <li v-for="text in voucher.warnings" :key="text">{{ text }}</li>
        </ul>
        <table class="grid voucher__lines">
          <thead><tr><th>摘要</th><th>科目编码</th><th>科目名称</th><th class="num">借方</th><th class="num">贷方</th><th>供应商</th><th>数量</th><th>待处理</th></tr></thead>
          <tbody>
            <tr v-for="line in voucher.lines" :key="line.row" :class="{ 'row--active': edits[line.row] }">
              <td><input :value="value(line, 'summary')" :aria-label="`第 ${line.row} 行摘要`" @input="edit(line, 'summary', ($event.target as HTMLInputElement).value)"></td>
              <td><input :value="value(line, 'code')" class="voucher__code" :aria-label="`第 ${line.row} 行科目编码`" @input="edit(line, 'code', ($event.target as HTMLInputElement).value)"></td>
              <td class="muted">{{ line.name }}</td>
              <td><input :value="value(line, 'debit')" class="voucher__amount" inputmode="decimal" :aria-label="`第 ${line.row} 行借方`" @input="edit(line, 'debit', ($event.target as HTMLInputElement).value)"></td>
              <td><input :value="value(line, 'credit')" class="voucher__amount" inputmode="decimal" :aria-label="`第 ${line.row} 行贷方`" @input="edit(line, 'credit', ($event.target as HTMLInputElement).value)"></td>
              <td><input :value="value(line, 'supplier')" :aria-label="`第 ${line.row} 行供应商`" @input="edit(line, 'supplier', ($event.target as HTMLInputElement).value)"></td>
              <td class="nowrap">{{ line.qty ? `${line.qty} ${line.unit}` : "" }}</td>
              <td :title="line.basis">{{ line.todo }}</td>
            </tr>
          </tbody>
        </table>
      </article>
      <p v-if="!shown.length" class="muted">没有符合条件的凭证。</p>
    </template>
  </section>
</template>
