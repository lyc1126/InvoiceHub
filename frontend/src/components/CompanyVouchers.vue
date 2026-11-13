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
interface DraftPayload { name: string; revision: string; books_error: string; vouchers: DraftVoucher[]; approved: number; blocked: number }
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

const keyOf = (voucher: DraftVoucher) => `${voucher.month}#${voucher.number}`;
const months = computed(() => [...new Set((draft.value?.vouchers ?? []).map((item) => item.month))]);
const shown = computed(() =>
  (draft.value?.vouchers ?? []).filter((item) => (!month.value || item.month === month.value) && (!onlyProblems.value || item.errors.length || refused.value[keyOf(item)])),
);
const dirtyCount = computed(() => {
  const keys = new Set(Object.keys(approvals));
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
      return lines.length || approval !== undefined ? { month: voucher.month, number: voucher.number, ...(approval !== undefined ? { approval } : {}), lines } : null;
    })
    .filter((item) => item !== null);
  try {
    const saved = await request<DraftPayload & { saved_rows: number; saved_approvals: number }>(
      `${base.value}/${encodeURIComponent(draft.value.name)}`,
      { method: "PUT", body: { revision: draft.value.revision, vouchers: changes } },
    );
    draft.value = saved;
    resetEdits();
    refused.value = {};
    notice.value = `已保存：改动 ${saved.saved_rows} 行、审核状态 ${saved.saved_approvals} 张。导出仍用 voucher_cli export 读取这份审核表。`;
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
    </div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <p v-if="files && !files.length" class="muted">
      公司资料夹 做账草稿/ 里还没有凭证审核表。先用 <code>python -m invoice_hub.bank.voucher_cli draft</code> 生成，再在这里审核和修改。
    </p>
    <template v-if="draft">
      <p class="banner banner--note">
        参考凭证需人工审核。共 {{ draft.vouchers.length }} 张，已通过 {{ draft.approved }} 张，有问题 {{ draft.blocked }} 张。
        改动过的凭证要重新审核；借贷不平或科目不可用时不能审核通过。保存只写这份审核表，不写 凭证/、不连接账套。
      </p>
      <p v-if="draft.books_error" class="banner banner--error" role="alert">{{ draft.books_error }}</p>

      <article
        v-for="voucher in shown"
        :key="keyOf(voucher)"
        class="voucher"
        :class="{ 'voucher--failed': voucher.errors.length || refused[keyOf(voucher)] }"
        :aria-label="`${voucher.month} 第 ${voucher.number} 号凭证`"
      >
        <header class="voucher__head">
          <strong>{{ voucher.month }} · 记-{{ voucher.number }}</strong>
          <span class="muted">{{ voucher.date }}</span>
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
