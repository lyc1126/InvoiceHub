<script setup lang="ts">
import WsModal from "./WsModal.vue";
import { useModulesStore } from "../stores/modules";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company } from "../api/types";
import { errorText, money } from "../format";
import MonthPicker from "./MonthPicker.vue";

// Voucher drafts (WS-05 stage 1): the CLI's review workbook in 做账草稿/, edited cell by cell.
// The page only shows a live debit/credit total while typing; the backend re-checks every
// voucher with the export rules on save and refuses to approve one that fails.
interface DraftLine {
  row: number; summary: string; code: string; name: string; debit: string | null; credit: string | null;
  supplier: string; qty: string | null; unit: string; todo: string; confidence: string; basis: string;
}
interface SourceDocument {
  kind: string; number: string; issue_date: string; book_month: string; cross: boolean; movable: boolean;
  override: { month: string; reason: string } | null;
}
interface DraftVoucher {
  month: string; number: string; date: string; approval: string; debit_total: string; credit_total: string;
  errors: string[]; warnings: string[]; lines: DraftLine[]; source_documents?: SourceDocument[];
}
interface DraftSheet { name: string; columns: (string | number)[]; rows: (string | number)[][]; truncated: boolean }
interface MonthStat { month: string; vouchers: number; approved: number; blocked: number; exported: number }
interface ExportPreview { format: string; columns: string[]; unmatched: string[]; sample_rows: (string | number | null)[][]; months: { month: string; approved: number; blocked_reason: string }[] }
interface DraftPayload {
  months?: MonthStat[];
  name: string; revision: string; books_error: string; vouchers: DraftVoucher[]; approved: number; blocked: number;
  sheets?: DraftSheet[]; current_month?: string;
  periods_revision?: number | null; periods_error?: string; cross_period_hint?: string;
}
interface Moved { from: { month: string; number: string }; to: { month: string; number: string } }
interface ExportFormat {
  key: string; label: string; status: "verified" | "experimental" | "custom"; note: string; file_suffix: string;
  usable?: boolean; unmatched?: string[]; missing?: string[];
}
interface DraftInputs { booked: string[]; ledgers: string[]; tax_file: boolean; current_month: string }
interface Carried { kept: string[]; review_again: string[]; new: string[]; gone: string[]; summaries_kept: number }
interface GenerateResult {
  name: string; tax_file_created: boolean; vouchers: number; low_confidence: number; missing_accounts: number; backup: string; carried: Carried | null;
}
interface ExportResult {
  files: string[]; exported: number; skipped: number; blocked_months: string[]; duplicates: string[]; learned: number;
  errors: { voucher: string; errors: string[] }[]; warnings: { voucher: string; warnings: string[] }[];
}
type Editable = "summary" | "code" | "debit" | "credit" | "supplier";

const props = withDefaults(defineProps<{ company: Company; layout?: "cards" | "split" }>(), { layout: "cards" });
const selectedVoucher = ref("");
const base = computed(() => `/api/v1/companies/${encodeURIComponent(props.company.id)}/voucher-drafts`);
const files = ref<{ name: string; months?: MonthStat[] }[] | null>(null);
const monthIndex = ref<MonthStat[]>([]);
// Generate (stage 2): voucher_cli draft from the page, with only the read-backs the backend listed.
const inputs = ref<DraftInputs | null>(null);
// Export formats (BK-01): built-in profiles plus the user's templates in 做账草稿/导出模板/.
const formats = ref<ExportFormat[]>([]);
const templateFolder = ref("");
const exportFormat = ref("jierui");
const chosenFormat = computed(() => formats.value.find((item) => item.key === exportFormat.value) ?? null);
const generateOpen = ref(false);
const generating = ref(false);
const generateResult = ref<GenerateResult | null>(null);
const plan = reactive({ from: "", to: "", monthEnd: true, booked: [] as string[], ledger: "" });
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
const added = reactive<Record<string, DraftLine[]>>({});
const removed = reactive<Record<string, number[]>>({});
const saveUnknown = ref(false);
let nextRow = -1;
function linesOf(voucher: DraftVoucher): DraftLine[] {
  return [...voucher.lines.filter(line => !removed[keyOf(voucher)]?.includes(line.row)), ...(added[keyOf(voucher)] ?? [])];
}
function addLine(voucher: DraftVoucher): void {
  (added[keyOf(voucher)] ??= []).push({ row: nextRow--, summary: "", code: "", name: "", debit: null, credit: null, supplier: "", qty: null, unit: "", todo: "新增分录，保存后校验", confidence: "", basis: "" });
}
function removeLine(voucher: DraftVoucher, line: DraftLine): void {
  if (linesOf(voucher).length <= 1) return;
  if (line.row < 0) added[keyOf(voucher)] = (added[keyOf(voucher)] ?? []).filter(item => item.row !== line.row);
  else (removed[keyOf(voucher)] ??= []).push(line.row);
  delete edits[line.row];
}
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
const exportJob = ref<{ url: string; token: string } | null>(null);
const approvedByMonth = computed(() => (draft.value?.months ?? []).filter(item => item.approved > 0 && (!month.value || item.month === month.value)).map(item => [item.month, item.approved] as const));
const preview = ref<ExportPreview | null>(null);
const previewing = ref(false);
let previewGeneration = 0;
let previewTimer: ReturnType<typeof setTimeout> | undefined;
const previewInput = () => JSON.stringify([exportOpen.value, draft.value?.name, draft.value?.revision, preparer.value, exportFormat.value, afterNumbers, month.value]);
function afterInput(): Record<string, number> {
  return Object.fromEntries(Object.entries(afterNumbers).filter(([, value]) => String(value ?? "").trim() !== "").map(([month, value]) => [month, Number(value)]));
}
watch(previewInput, () => {
  const mine = ++previewGeneration;
  clearTimeout(previewTimer);
  preview.value = null;
  previewing.value = false;
  if (!exportOpen.value || !draft.value || !preparer.value.trim()) return;
  previewing.value = true;
  previewTimer = setTimeout(async () => {
    try {
      const result = await request<ExportPreview>(`${base.value}/${encodeURIComponent(draft.value!.name)}/export`, {
        method: "POST", body: { revision: draft.value!.revision, preparer: preparer.value, after: afterInput(), format: exportFormat.value, month: month.value, dry_run: true },
      });
      if (mine === previewGeneration) preview.value = result;
    } catch (cause) { if (mine === previewGeneration) error.value = errorText(cause); }
    finally { if (mine === previewGeneration) previewing.value = false; }
  }, 300);
});
onBeforeUnmount(() => { clearTimeout(previewTimer); previewGeneration += 1; filesGeneration += 1; draftGeneration += 1; });
// 改记入期 (stage 2a): corrects generated data only; the invoice file stays where it is.
const REBOOK_REASONS = ["次月到票", "补记漏记", "月末暂估", "开票日期有误", "其他"];
const rebooking = ref<{ key: string; number: string; issueMonth: string; month: string; reason: string; override: boolean } | null>(null);
const rebookBusy = ref(false);
const numberFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 });
const cellText = (value: string | number) => (typeof value === "number" ? numberFormat.format(value) : value);

const keyOf = (voucher: DraftVoucher) => `${voucher.month}#${voucher.number}`;
const months = computed(() => monthIndex.value.map(item => item.month));
const shown = computed(() =>
  (draft.value?.vouchers ?? []).filter((item) => (!month.value || item.month === month.value) && (!onlyProblems.value || item.errors.length || refused.value[keyOf(item)])),
);
const dirtyCount = computed(() => {
  const keys = new Set([...Object.keys(approvals), ...Object.keys(periods), ...Object.keys(added).filter(key => added[key]?.length), ...Object.keys(removed).filter(key => removed[key]?.length)]);
  for (const voucher of draft.value?.vouchers ?? []) if (voucher.lines.some((line) => edits[line.row])) keys.add(keyOf(voucher));
  return keys.size;
});
// Split layout lives under the bookkeeping page head; mirror month / export state into the
// shared module store so the head can drive them (prototype bkView head).
const modulesStore = useModulesStore();
function bookEntry() {
  if (props.layout !== "split") return null;
  return (modulesStore.book[props.company.id] ??= { month: "", months: [], approved: 0, exportable: false, exportTick: 0 });
}
watch(() => [props.company.id, months.value.join(","), month.value, draft.value?.months, dirtyCount.value, exporting.value, exportJob.value, loading.value, saving.value, saveUnknown.value] as const, () => {
  const state = bookEntry();
  if (!state) return;
  // Head count = approved but not yet exported (backend month index); exported ones would be skipped.
  state.months = months.value; state.month = month.value;
  state.approved = (draft.value?.months ?? []).filter(item => !month.value || item.month === month.value).reduce((sum, item) => sum + Math.max(0, item.approved - item.exported), 0);
  state.exportable = state.approved > 0 && dirtyCount.value === 0 && !exporting.value && !exportJob.value && !loading.value && !saving.value && !saveUnknown.value;
}, { immediate: true });
watch(() => props.layout === "split" ? modulesStore.book[props.company.id]?.month : undefined, value => { if (value !== undefined && value !== month.value) month.value = value; });
watch(() => props.layout === "split" ? modulesStore.book[props.company.id]?.exportTick : undefined, (tick, old) => {
  if (tick && tick !== old && bookEntry()?.exportable) { exportOpen.value = true; exportResult.value = null; }
});

function value(line: DraftLine, field: Editable): string {
  return edits[line.row]?.[field] ?? line[field] ?? "";
}

function edit(line: DraftLine, field: Editable, text: string): void {
  if (saving.value || saveUnknown.value) return;
  const next = { ...edits[line.row], [field]: text };
  if (text === (line[field] ?? "")) delete next[field];
  if (Object.keys(next).length) edits[line.row] = next;
  else delete edits[line.row];
}

function cents(text: string): bigint | null {
  const cleaned = text.replace(/,/g, "").trim();
  if (!cleaned) return 0n;
  if (!/^-?\d{1,18}(\.\d{1,2})?$/.test(cleaned)) return null;
  const [whole = "0", fraction = ""] = cleaned.replace(/^-/, "").split(".");
  return (BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"))) * (cleaned.startsWith("-") ? -1n : 1n);
}

// Display only: the live totals while typing. The backend's check on save is what counts.
function totals(voucher: DraftVoucher): { debit: string; credit: string; balanced: boolean; readable: boolean } {
  let debit = 0n;
  let credit = 0n;
  let readable = true;
  for (const line of linesOf(voucher)) {
    const d = cents(value(line, "debit"));
    const c = cents(value(line, "credit"));
    if (d === null || c === null) readable = false;
    debit += d ?? 0n;
    credit += c ?? 0n;
  }
  const show = (amount: bigint) => {
    const digits = (amount < 0n ? -amount : amount).toString().padStart(3, "0");
    return `${amount < 0n ? '-' : ''}${digits.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${digits.slice(-2)}`;
  };
  return { debit: show(debit), credit: show(credit), balanced: readable && debit === credit, readable };
}

function approvalOf(voucher: DraftVoucher): string {
  return approvals[keyOf(voucher)] ?? voucher.approval;
}

function resetEdits(): void {
  for (const key of Object.keys(edits)) delete edits[Number(key)];
  for (const key of Object.keys(approvals)) delete approvals[key];
  for (const key of Object.keys(periods)) delete periods[key];
  for (const key of Object.keys(added)) delete added[key];
  for (const key of Object.keys(removed)) delete removed[key];
}

function periodOf(voucher: DraftVoucher): { month: string; date: string } {
  return periods[keyOf(voucher)] ?? { month: voucher.month, date: voucher.date };
}

function lastDay(month: string): string {
  const [year, number] = month.split("-").map(Number);
  return `${month}-${String(new Date(year!, number!, 0).getDate()).padStart(2, "0")}`;
}

function setPeriod(voucher: DraftVoucher, field: "month" | "date", value: string): void {
  if (!value || saving.value || saveUnknown.value) return;
  const next = { ...periodOf(voucher), [field]: value };
  // A new month moves the date to its last day (the draft's month-end convention) unless it already fits.
  if (field === "month" && !next.date.startsWith(`${value}-`)) next.date = lastDay(value);
  if (next.month === voucher.month && next.date === voucher.date) delete periods[keyOf(voucher)];
  else periods[keyOf(voucher)] = next;
}

let filesGeneration = 0;
let draftGeneration = 0;
async function loadFiles(): Promise<void> {
  const mine = ++filesGeneration;
  error.value = "";
  try {
    const listing = await request<{ drafts: { name: string; months?: MonthStat[] }[]; months?: MonthStat[]; index_errors?: { name: string; message: string }[]; inputs: DraftInputs; formats?: ExportFormat[]; template_folder?: string }>(base.value);
    if (mine !== filesGeneration) return;
    files.value = listing.drafts;
    monthIndex.value = listing.months ?? [];
    if (listing.index_errors?.length) error.value = listing.index_errors.map(item => `${item.name}：${item.message}`).join("；");
    inputs.value = listing.inputs;
    formats.value = listing.formats ?? [];
    templateFolder.value = listing.template_folder ?? "";
    if (!formats.value.some((item) => item.key === exportFormat.value)) exportFormat.value = "jierui";
    if (!files.value.some((item) => item.name === selectedFile.value)) selectedFile.value = files.value.at(-1)?.name ?? "";
  } catch (cause) {
    if (mine === filesGeneration) error.value = errorText(cause);
  }
}

async function loadDraft(): Promise<boolean> {
  const mine = ++draftGeneration;
  if (!selectedFile.value) {
    draft.value = null;
    return false;
  }
  loading.value = true;
  if (draft.value?.name !== selectedFile.value) draft.value = null;
  error.value = "";
  try {
    const result = await request<DraftPayload>(`${base.value}/${encodeURIComponent(selectedFile.value)}`);
    if (mine !== draftGeneration) return false;
    draft.value = result;
    const file = files.value?.find(item => item.name === draft.value?.name);
    if (file && draft.value.months) file.months = draft.value.months;
    resetEdits();
    refused.value = {};
    if (month.value && !months.value.includes(month.value)) month.value = "";
    return true;
  } catch (cause) {
    if (mine === draftGeneration) error.value = errorText(cause);
    return false;
  } finally {
    if (mine === draftGeneration) loading.value = false;
  }
}

async function querySaved(): Promise<void> {
  // Only a successful read releases unknown state; failures must never re-enable save.
  if (await loadDraft()) {
    saveUnknown.value = false;
    notice.value = "已重新读取审核表，请核对保存结果；未重放改动。";
  }
}

async function save(): Promise<void> {
  if (!draft.value || !dirtyCount.value || saving.value || saveUnknown.value) return;
  saving.value = true;
  const mine = draftGeneration;
  error.value = "";
  notice.value = "";
  const changes = draft.value.vouchers
    .map((voucher) => {
      const lines = voucher.lines.filter((line) => edits[line.row]).map((line) => ({ row: line.row, ...edits[line.row] }));
      const approval = approvals[keyOf(voucher)];
      const period = periods[keyOf(voucher)];
      const addLines = (added[keyOf(voucher)] ?? []).map(line => ({ row: line.row, ...Object.fromEntries((["summary", "code", "debit", "credit", "supplier"] as Editable[]).map(field => [field, value(line, field)])) }));
      const deleteRows = removed[keyOf(voucher)] ?? [];
      if (!lines.length && approval === undefined && !period && !addLines.length && !deleteRows.length) return null;
      return {
        month: voucher.month, number: voucher.number, ...(approval !== undefined ? { approval } : {}),
        ...(period ? { move_month: period.month, date: period.date } : {}), lines, ...(addLines.length ? { add_lines: addLines } : {}), ...(deleteRows.length ? { delete_rows: deleteRows } : {}),
      };
    })
    .filter((item) => item !== null);
  try {
    const saved = await request<DraftPayload & { saved_rows: number; saved_approvals: number; moved: Moved[] }>(
      `${base.value}/${encodeURIComponent(draft.value.name)}`,
      { method: "PUT", body: { revision: draft.value.revision, vouchers: changes } },
    );
    if (mine !== draftGeneration) return;
    draft.value = saved;
    await loadFiles();
    if (mine !== draftGeneration) return;
    resetEdits();
    refused.value = {};
    const movedAll = saved.moved ?? [];
    const moved = movedAll.filter((item) => item.from.month !== item.to.month || item.from.number !== item.to.number)
      .map((item) => `${item.from.month} 第 ${item.from.number} 号 → ${item.to.month} 第 ${item.to.number} 号`);
    notice.value = `已保存：改动 ${saved.saved_rows} 行、审核状态 ${saved.saved_approvals} 张${movedAll.length ? `、所属期 / 日期 ${movedAll.length} 张` : ""}。`
      + (moved.length ? `移动后重新编号：${moved.join("；")}。` : "");
  } catch (cause) {
    if (mine !== draftGeneration) return;
    if (cause instanceof ApiError && cause.code === "VOUCHER_DRAFT_CONFLICT") {
      await loadDraft();
      error.value = "审核表已在别处修改（或重新生成），已刷新，请重新编辑。";
    } else if (cause instanceof ApiError && cause.code === "VOUCHER_DRAFT_NOT_APPROVABLE") {
      // Nothing was written; the edits stay on the page next to the reasons.
      refused.value = Object.fromEntries((cause.details as { month: string; number: string; errors: string[] }[]).map((item) => [`${item.month}#${item.number}`, item.errors]));
      error.value = "有凭证未通过校验，不能审核通过；未保存任何改动。";
    } else {
      error.value = errorText(cause);
      saveUnknown.value = !(cause instanceof ApiError && cause.status >= 400 && cause.status < 500);
    }
  } finally {
    if (mine === draftGeneration) saving.value = false;
  }
}

function openGenerate(): void {
  generateOpen.value = !generateOpen.value;
  generateResult.value = null;
  if (!generateOpen.value || !inputs.value) return;
  // Defaults: the open table's range, every 序时账 read-back, the newest 科目表 snapshot.
  const match = /^凭证草稿_(\d{4}-\d{2})_(\d{4}-\d{2})\.xlsx$/.exec(selectedFile.value);
  plan.from = match?.[1] ?? inputs.value.current_month;
  plan.to = match?.[2] ?? inputs.value.current_month;
  plan.booked = [...inputs.value.booked];
  plan.ledger = inputs.value.ledgers.at(-1) ?? "";
}

const replaces = computed(() => files.value?.some((item) => item.name === `凭证草稿_${plan.from}_${plan.to}.xlsx`) ?? false);

async function runGenerate(): Promise<void> {
  generating.value = true;
  error.value = "";
  try {
    const result = await request<GenerateResult>(base.value, {
      method: "POST", timeoutMs: 180_000,
      body: { from: plan.from, to: plan.to, month_end: plan.monthEnd, booked: plan.booked, ledger: plan.ledger || null, confirm: true },
    });
    generateResult.value = result;
    generateOpen.value = false;
    await loadFiles();
    // Same name as before: the watcher would not fire, so read it explicitly.
    if (selectedFile.value === result.name) await loadDraft();
    else selectedFile.value = result.name;
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    generating.value = false;
  }
}

function startRebook(voucher: DraftVoucher, doc: SourceDocument): void {
  rebooking.value = { key: keyOf(voucher), number: doc.number, issueMonth: doc.issue_date.slice(0, 7), month: voucher.month,
    reason: doc.override?.reason || REBOOK_REASONS[0]!, override: !!doc.override };
}

async function runRebook(back = false): Promise<void> {
  if (!draft.value || !rebooking.value) return;
  rebookBusy.value = true;
  error.value = "";
  notice.value = "";
  const target = back ? "" : rebooking.value.month;
  try {
    const result = await request<{ out_of_range: boolean; generation_remembered: boolean; generated: GenerateResult }>(
      `${base.value}/${encodeURIComponent(draft.value.name)}/rebook`,
      { method: "POST", timeoutMs: 180_000,
        body: { revision: draft.value.periods_revision ?? 0, number: rebooking.value.number, month: target, reason: back ? "" : rebooking.value.reason } },
    );
    const where = target || rebooking.value.issueMonth;
    notice.value = `发票 …${rebooking.value.number.slice(-8)} 已${back ? "恢复为开票月" : "改记入"} ${where}，草稿已重新生成。`
      + (result.out_of_range ? `${where} 不在本表范围内，生成该月草稿后会出现在那里。` : "")
      + (result.generation_remembered ? "" : "（本表不是在页面生成的，已按文件名的起止月、统一记月末与全部读回重新生成。）");
    generateResult.value = result.generated;
    rebooking.value = null;
    await loadDraft();
  } catch (cause) {
    if (cause instanceof ApiError && cause.code === "VOUCHER_PERIODS_CONFLICT") {
      await loadDraft();
      error.value = "记入期调整已在别处修改，已刷新，请重新操作。";
    } else {
      error.value = errorText(cause);
    }
  } finally {
    rebookBusy.value = false;
  }
}

async function runExport(): Promise<void> {
  if (!draft.value || !preview.value || previewing.value || exportJob.value || loading.value || draft.value.name !== selectedFile.value) return;
  exporting.value = true;
  error.value = "";
  exportResult.value = null;
  const after = Object.fromEntries(Object.entries(afterNumbers).filter(([, value]) => String(value ?? "").trim() !== "").map(([month, value]) => [month, Number(value)]));
  const token = crypto.randomUUID();
  const url = `${base.value}/${encodeURIComponent(draft.value.name)}`;
  exportJob.value = { url, token };
  try {
    exportResult.value = await request<ExportResult>(`${base.value}/${encodeURIComponent(draft.value.name)}/export`, {
      method: "POST", body: { revision: draft.value.revision, preparer: preparer.value, after, format: exportFormat.value, month: month.value, request_id: token, confirm: true }, timeoutMs: 60_000,
    });
    exportJob.value = null;
    exportOpen.value = false;
    await loadFiles();
    await loadDraft();
  } catch (cause) {
    if (cause instanceof ApiError && cause.code === "VOUCHER_DRAFT_CONFLICT") {
      await loadDraft();
      error.value = "审核表已在别处修改（或重新生成），已刷新，请重新核对后再导出。";
      exportJob.value = null;
    } else {
      error.value = errorText(cause);
      // One GET, never a re-POST: a receipt the server marked "rejected" proves nothing was
      // written and releases the button; unknown/unreachable keeps the query-only state.
      exporting.value = false;
      await readExportResult(true);
    }
  } finally {
    exporting.value = false;
  }
}

async function readExportResult(quiet = false): Promise<void> {
  if (!exportJob.value || exporting.value) return;
  exporting.value = true;
  try {
    const result = await request<ExportResult & { state: string; message: string }>(`${exportJob.value.url}/export-jobs/${exportJob.value.token}`);
    if (result.state === "completed") {
      exportResult.value = result;
      exportJob.value = null;
      exportOpen.value = false;
      await loadFiles();
      await loadDraft();
    } else if (result.state === "rejected") {
      exportJob.value = null;
      error.value = result.message;
    } else if (!quiet) error.value = result.message;
  } catch (cause) { if (!quiet) error.value = errorText(cause); }
  finally { exporting.value = false; }
}

watch(selectedFile, () => void loadDraft());
watch(month, value => {
  if (!value || saving.value || saveUnknown.value || dirtyCount.value || files.value?.find(item => item.name === selectedFile.value)?.months?.some(item => item.month === value)) return;
  const file = files.value?.find(item => item.months?.some(item => item.month === value));
  if (file) selectedFile.value = file.name;
});
watch(
  () => props.company.id,
  () => {
    filesGeneration += 1; draftGeneration += 1;
    files.value = null;
    selectedFile.value = "";
    draft.value = null;
    saveUnknown.value = false; saving.value = false; resetEdits();
    void loadFiles();
  },
  { immediate: true },
);
</script>

<template>
  <section aria-label="凭证草稿">
    <div class="toolbar">
      <select v-if="files?.length" :disabled="saving || saveUnknown || dirtyCount > 0" v-model="selectedFile" aria-label="审核表">
        <option v-for="file in files ?? []" :key="file.name" :value="file.name">{{ file.name }}</option>
      </select>
      <select v-if="months.length > 1" v-model="month" aria-label="月份">
        <option value="">全部月份</option>
        <option v-for="item in months" :key="item" :value="item">{{ item }}</option>
      </select>
      <label v-if="files?.length" class="nowrap"><input v-model="onlyProblems" type="checkbox"> 只看有问题的</label>
      <button type="button" :disabled="loading || saving || saveUnknown || dirtyCount > 0" @click="loadFiles().then(loadDraft)">重新读取</button>
      <button v-if="files?.length" type="button" class="primary" :disabled="saving || saveUnknown || !dirtyCount" :aria-busy="saving" @click="save">
        {{ saving ? "保存中…" : `保存（${dirtyCount} 张）` }}
      </button>
      <button v-if="saveUnknown" type="button" :disabled="loading" @click="querySaved">查询审核表</button>
      <button v-if="files?.length" type="button" :disabled="!inputs || generating || saving || saveUnknown || dirtyCount > 0" :title="dirtyCount ? '先保存改动再生成' : ''" @click="openGenerate">生成草稿…</button>
      <button
        v-if="files?.length"
        type="button"
        :disabled="!draft || !draft.approved || dirtyCount > 0 || exporting || saving || saveUnknown"
        :title="dirtyCount ? '先保存改动再导出' : !draft?.approved ? '还没有审核通过的凭证' : ''"
        @click="exportOpen = !exportOpen; exportResult = null"
      >导出已审核…</button>
    </div>
    <section v-if="generateOpen && inputs" class="panel" role="group" aria-label="生成凭证草稿">
      <p>
        按银行流水、发票明细、申报数据.json 与读回的账套生成参考凭证（与命令行 voucher_cli draft 相同），写到 做账草稿/。
        <template v-if="replaces">已有同期审核表：先备份到 做账草稿/历史/，内容没变的凭证沿用审核与改过的摘要，变了的列出来重新审核。</template>
      </p>
      <p v-if="!inputs.tax_file" class="banner banner--note">还没有 申报数据.json：生成时会按流水写一份模板，请按申报表补填后再生成一次。</p>
      <div class="toolbar">
        <label class="nowrap">从 <input v-model="plan.from" type="month" :max="inputs.current_month" aria-label="起始月份"></label>
        <label class="nowrap">到 <input v-model="plan.to" type="month" :max="inputs.current_month" aria-label="结束月份"></label>
        <label class="nowrap"><input v-model="plan.monthEnd" type="checkbox"> 凭证统一记在月末（收付款摘要前写实际日期）</label>
      </div>
      <fieldset v-if="inputs.booked.length" class="voucher__readback">
        <legend>已入账月份的序时账读回（做账草稿/账套读回/）</legend>
        <label v-for="item in inputs.booked" :key="item" class="nowrap"><input v-model="plan.booked" type="checkbox" :value="item"> {{ item }}</label>
      </fieldset>
      <label v-if="inputs.ledgers.length" class="nowrap">科目表
        <select v-model="plan.ledger" aria-label="科目表">
          <option value="">凭证/科目表.json</option>
          <option v-for="item in inputs.ledgers" :key="item" :value="item">账套读回/{{ item }}</option>
        </select>
      </label>
      <div class="toolbar">
        <button type="button" class="primary" :disabled="generating || !plan.from || !plan.to || plan.from > plan.to" :aria-busy="generating" @click="runGenerate">
          {{ generating ? "生成中…" : replaces ? "备份并重新生成" : "生成" }}
        </button>
        <button type="button" @click="generateOpen = false">取消</button>
      </div>
    </section>
    <section v-if="generateResult" class="panel" role="status" aria-label="生成结果">
      <p>
        已生成 {{ generateResult.name }}：{{ generateResult.vouchers }} 张凭证（低置信度 {{ generateResult.low_confidence }} 张），待补科目 {{ generateResult.missing_accounts }} 项。
        <template v-if="generateResult.backup">旧表已备份到 做账草稿/{{ generateResult.backup }}。</template>
      </p>
      <p v-if="generateResult.tax_file_created" class="banner banner--note">已写出 申报数据.json 模板：请按申报表补填已申报 / 未申报与税额后重新生成。</p>
      <template v-if="generateResult.carried">
        <p>沿用审核 {{ generateResult.carried.kept.length }} 张、沿用改过的摘要 {{ generateResult.carried.summaries_kept }} 行。</p>
        <details v-if="generateResult.carried.review_again.length" open>
          <summary class="check--failed">内容变了、需要重新审核 {{ generateResult.carried.review_again.length }} 张</summary>
          <ul class="warnings warnings--compact"><li v-for="item in generateResult.carried.review_again" :key="item">{{ item }}</li></ul>
        </details>
        <details v-if="generateResult.carried.new.length">
          <summary>新增 {{ generateResult.carried.new.length }} 张</summary>
          <ul class="warnings warnings--compact"><li v-for="item in generateResult.carried.new" :key="item">{{ item }}</li></ul>
        </details>
        <details v-if="generateResult.carried.gone.length">
          <summary>旧表有、新表没有 {{ generateResult.carried.gone.length }} 张</summary>
          <ul class="warnings warnings--compact"><li v-for="item in generateResult.carried.gone" :key="item">{{ item }}</li></ul>
        </details>
      </template>
    </section>
    <!-- Prototype openExport(): a wide dialog; the confirm / unknown-result rules are unchanged. -->
    <WsModal v-if="exportOpen && draft" title="导出凭证" subtitle="只导出审核通过的凭证，写到公司资料夹 做账草稿/，不连接账套。" :wide="true" @close="exportOpen = false">
    <section role="group" aria-label="导出已审核凭证">
      <p>
        将 {{ month || "本审核表全部月份" }} 中审核为“通过”的凭证导出为{{ chosenFormat?.label ?? "账套" }}导入文件，写到公司资料夹 做账草稿/，由会计人员在账套中手工导入（不连接账套）。
        某月有凭证校验不通过时该月整月不导出；已导出过的凭证会跳过，不会重复导出。
      </p>
      <div class="overview-table-wrap export-setup-table"><table class="grid">
        <thead><tr><th>月份</th><th class="num">通过</th><th>账套该月已用到的凭证号（没有可空）</th></tr></thead>
        <tbody>
          <tr v-for="[month, count] in approvedByMonth" :key="month">
            <td>{{ month }}</td>
            <td class="num">{{ count }}</td>
            <td><input v-model="afterNumbers[month]" type="number" min="0" max="999" inputmode="numeric" :aria-label="`${month} 账套已用到的凭证号`"></td>
          </tr>
        </tbody>
      </table></div>
      <div v-if="formats.length" class="toolbar">
        <label class="nowrap">导出格式
          <select v-model="exportFormat" aria-label="导出格式">
            <option v-for="item in formats" :key="item.key" :value="item.key" :disabled="item.usable === false">
              {{ item.label }}{{ item.status === "verified" ? "（已实测）" : item.status === "experimental" ? "（实验，未经实际导入验证）" : "（自定义模板）" }}{{ item.usable === false ? " - 缺列不可用" : "" }}
            </option>
          </select>
        </label>
        <span class="muted">其他软件：把自家账套下载的空白导入模板放进 {{ templateFolder }}/，按表头自动对列。</span>
      </div>
      <p v-if="chosenFormat && chosenFormat.status !== 'verified'" class="banner banner--error" role="note">
        {{ chosenFormat.status === "experimental" ? "实验格式，未经实际导入验证：" : "自定义模板：" }}{{ chosenFormat.note }}
        <template v-if="chosenFormat.unmatched?.length">对不上、将留空的列：{{ chosenFormat.unmatched.join("、") }}。</template>
        请先只把一张凭证标“通过”导入核对。
      </p>
      <p v-if="previewing" class="muted" aria-busy="true">正在预览导出…</p>
      <section v-if="preview" aria-label="导出预览">
        <div class="export-cols"><span v-for="column in preview.columns" :key="column" class="tag">{{ column }}</span></div>
        <p v-if="preview.unmatched.length" class="muted">未匹配列（留空）：{{ preview.unmatched.join('、') }}</p>
        <p v-for="item in preview.months.filter(item => item.blocked_reason)" :key="item.month" class="banner banner--error">{{ item.month }} 整月阻断：{{ item.blocked_reason }}</p>
        <div class="overview-table-wrap"><table class="grid"><thead><tr><th v-for="(column, index) in preview.columns" :key="index">{{ column }}</th></tr></thead>
          <tbody><tr v-for="(row, index) in preview.sample_rows" :key="index"><td v-for="(cell, col) in row" :key="col">{{ cell ?? '' }}</td></tr></tbody>
        </table></div>
        <p class="muted">最多预览 5 行，不写文件、不标记已导出；确认时重新校验。</p>
      </section>
      <p v-if="exportJob" role="status">导出请求已发出；响应未知时只读取结果，不能再次提交。</p>
      <div class="toolbar">
        <button v-if="exportJob" type="button" :disabled="exporting" @click="readExportResult()">读取导出结果</button>
        <label class="nowrap">制单人 <input v-model="preparer" maxlength="20" aria-label="制单人" placeholder="与账套里的制单人一致"></label>
        <button type="button" class="primary" :disabled="exporting || !!exportJob || !preparer.trim() || !preview || previewing" :aria-busy="exporting" @click="runExport">{{ exporting ? "导出中…" : "确认导出" }}</button>
        <button type="button" class="ghost" @click="exportOpen = false">取消</button>
      </div>
    </section>
    </WsModal>
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
    <div v-if="files && !files.length" class="empty-state">
      <b>还没有凭证草稿</b>
      <span>公司资料夹 做账草稿/ 里还没有凭证审核表。点“生成草稿…”生成，再在这里审核和修改。</span>
      <button type="button" class="primary" :disabled="!inputs || generating" @click="openGenerate">生成草稿…</button>
    </div>
    <template v-if="draft">
      <p class="banner banner--note">
        参考凭证需人工审核。共 {{ draft.vouchers.length }} 张，已通过 {{ draft.approved }} 张，有问题 {{ draft.blocked }} 张。
        改动过的凭证（含所属期、记账日期）要重新审核；借贷不平、科目不可用或记账日期不在所属期内时不能审核通过。保存只写这份审核表，导出只写 做账草稿/，都不写 凭证/、不连接账套。
      </p>
      <p v-if="draft.books_error" class="banner banner--error" role="alert">{{ draft.books_error }}</p>
      <p v-if="draft.periods_error" class="banner banner--error" role="alert">{{ draft.periods_error }}</p>
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

      <div :class="{ 'voucher-workbench': layout === 'split' }">
      <nav v-if="layout === 'split'" class="voucher-list" aria-label="选择凭证草稿">
        <button v-for="voucher in shown" :key="keyOf(voucher)" type="button" :aria-pressed="keyOf(voucher) === (shown.some(item => keyOf(item) === selectedVoucher) ? selectedVoucher : shown[0] && keyOf(shown[0]))" @click="selectedVoucher = keyOf(voucher)">
          <span class="voucher-list__number">记-{{ voucher.number }}</span><strong>{{ voucher.lines[0]?.summary || '凭证草稿' }}</strong>
          <span class="tag" :class="voucher.errors.length ? 'tag--danger' : approvalOf(voucher) === '通过' ? 'pill-ok' : 'pill-warn'">{{ voucher.errors.length ? '阻断' : approvalOf(voucher) === '通过' ? '已通过' : '待审核' }}</span>
          <small>{{ voucher.month }} · {{ money(voucher.debit_total) }}</small>
        </button>
      </nav>
      <div class="voucher-editor">
      <article
        v-for="voucher in shown"
        v-show="layout !== 'split' || keyOf(voucher) === (shown.some(item => keyOf(item) === selectedVoucher) ? selectedVoucher : shown[0] && keyOf(shown[0]))"
        :key="keyOf(voucher)"
        class="voucher"
        :class="{ 'voucher--failed': voucher.errors.length || refused[keyOf(voucher)] }"
        :aria-label="`${voucher.month} 第 ${voucher.number} 号凭证`"
      >
        <header class="voucher__head">
          <strong>{{ voucher.month }} · 记-{{ voucher.number }}</strong>
          <span class="muted">改过的凭证需要保存后重新审核</span>
          <select
            :value="approvalOf(voucher)"
            :disabled="saving || saveUnknown"
            :aria-label="`${voucher.month} 第 ${voucher.number} 号凭证审核`"
            @change="approvals[keyOf(voucher)] = ($event.target as HTMLSelectElement).value"
          ><option value="">待审核</option><option value="通过">通过</option><option value="不导入">不导入</option></select>
        </header>
        <fieldset class="voucher-period-row" :disabled="saving || saveUnknown">
          <label class="nowrap">所属期
            <MonthPicker
              :model-value="periodOf(voucher).month"
              :max="draft.current_month"
              :label="`${voucher.month} 第 ${voucher.number} 号凭证所属期`"
              @update:model-value="setPeriod(voucher, 'month', $event)"
            />
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
          <span :class="periodOf(voucher).date.startsWith(periodOf(voucher).month) ? 'muted' : 'check--failed'">{{ periodOf(voucher).date.startsWith(periodOf(voucher).month) ? '记账日期在所属期内' : '记账日期不在所属期内，不能审核' }}</span>
        </fieldset>
        <p v-for="doc in voucher.source_documents ?? []" :key="doc.kind + doc.number" class="voucher__source">
          原始单据：{{ doc.kind }}<template v-if="doc.number"> …{{ doc.number.slice(-8) }}</template><template v-if="doc.issue_date"> · 开票 {{ doc.issue_date }}</template>
          <span class="tag" :class="{ 'tag--danger': doc.cross }" :title="doc.cross ? draft.cross_period_hint : '单据日期与记入期在同一个月'">{{ doc.cross ? "跨期" : "同期" }}</span>
          <span v-if="doc.override" class="muted">人工调整记入期{{ doc.override.reason ? `（${doc.override.reason}）` : "" }}</span>
          <button v-if="doc.movable && doc.number" type="button" class="link" :disabled="!!dirtyCount" :title="dirtyCount ? '先保存改动' : ''" @click="startRebook(voucher, doc)">改记入期</button>
          <span v-else-if="!doc.movable" class="muted">按对账单入账日记账，不能单独改记入期</span>
        </p>
        <div v-if="rebooking?.key === keyOf(voucher)" class="toolbar" role="group" :aria-label="`改记入期 ${voucher.month} 第 ${voucher.number} 号凭证`">
          <label class="nowrap">记入期 <input v-model="rebooking.month" type="month" :max="draft.current_month" aria-label="记入期"></label>
          <label class="nowrap">原因
            <select v-model="rebooking.reason" aria-label="改记入期原因"><option v-for="item in REBOOK_REASONS" :key="item" :value="item">{{ item }}</option></select>
          </label>
          <button type="button" class="primary" :disabled="rebookBusy || !rebooking.month" :aria-busy="rebookBusy" @click="runRebook()">{{ rebookBusy ? "重新生成中…" : "保存并重新生成" }}</button>
          <button v-if="rebooking.override" type="button" :disabled="rebookBusy" @click="runRebook(true)">恢复为开票月</button>
          <button type="button" :disabled="rebookBusy" @click="rebooking = null">取消</button>
          <span class="muted">只改凭证的记入期，不移动发票文件；改动过的凭证需要重新审核。</span>
        </div>
        <p v-if="periods[keyOf(voucher)] && periods[keyOf(voucher)]!.month !== voucher.month" class="muted voucher__stale">
          保存后移到 {{ periods[keyOf(voucher)]!.month }}，并接在该月已有凭证号之后重新编号；需要重新审核。
        </p>
        <p v-if="!refused[keyOf(voucher)] && voucher.errors.length && (voucher.lines.some((line) => edits[line.row]) || added[keyOf(voucher)]?.length || removed[keyOf(voucher)]?.length)" class="muted voucher__stale">
          下面是上次保存时的校验结果，保存后重新校验。
        </p>
        <ul v-if="refused[keyOf(voucher)] || voucher.errors.length" class="warnings warnings--compact">
          <li v-for="text in refused[keyOf(voucher)] ?? voucher.errors" :key="text" class="check--failed">{{ text }}</li>
        </ul>
        <ul v-if="voucher.warnings.length" class="warnings warnings--compact">
          <li v-for="text in voucher.warnings" :key="text">{{ text }}</li>
        </ul>
        <div class="overview-table-wrap"><table class="grid voucher__lines">
          <thead><tr><th>摘要</th><th>科目编码</th><th>科目名称</th><th class="num">借方</th><th class="num">贷方</th><th>供应商</th><th>数量</th><th>待处理</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="line in linesOf(voucher)" :key="line.row" :class="{ 'row--active': edits[line.row] || line.row < 0 }">
              <td><input :disabled="saving || saveUnknown" :value="value(line, 'summary')" :aria-label="`第 ${line.row} 行摘要`" @input="edit(line, 'summary', ($event.target as HTMLInputElement).value)"></td>
              <td><input :disabled="saving || saveUnknown" :value="value(line, 'code')" class="voucher__code" :aria-label="`第 ${line.row} 行科目编码`" @input="edit(line, 'code', ($event.target as HTMLInputElement).value)"></td>
              <td class="muted">{{ line.name }}</td>
              <td><input :disabled="saving || saveUnknown" :value="value(line, 'debit')" class="voucher__amount" inputmode="decimal" :aria-label="`第 ${line.row} 行借方`" @input="edit(line, 'debit', ($event.target as HTMLInputElement).value)"></td>
              <td><input :disabled="saving || saveUnknown" :value="value(line, 'credit')" class="voucher__amount" inputmode="decimal" :aria-label="`第 ${line.row} 行贷方`" @input="edit(line, 'credit', ($event.target as HTMLInputElement).value)"></td>
              <td><input :disabled="saving || saveUnknown" :value="value(line, 'supplier')" :aria-label="`第 ${line.row} 行供应商`" @input="edit(line, 'supplier', ($event.target as HTMLInputElement).value)"></td>
              <td class="nowrap">{{ line.qty ? `${line.qty} ${line.unit}` : "" }}</td>
              <td :title="line.basis">{{ line.todo }}</td>
              <td><button type="button" class="ghost" :aria-label="`删除第 ${line.row} 行`" :disabled="saving || saveUnknown || linesOf(voucher).length <= 1" @click="removeLine(voucher, line)">×</button></td>
            </tr>
          </tbody>
          <tfoot><tr><th colspan="3">合计 <span :class="totals(voucher).balanced ? 'muted' : 'check--failed'">{{ !totals(voucher).readable ? '金额无法识别' : totals(voucher).balanced ? '借贷平衡' : '借贷不平' }}</span></th><td class="num">{{ totals(voucher).debit }}</td><td class="num">{{ totals(voucher).credit }}</td><td colspan="4"></td></tr></tfoot>
        </table></div>
        <div class="toolbar"><button type="button" :disabled="saving || saveUnknown || linesOf(voucher).length >= 500" @click="addLine(voucher)">加一行</button><span class="muted">改过的凭证要重新审核；导出时还会校验科目、借贷和重复导出。</span></div>
      </article>
      </div>
      </div>
      <p v-if="!shown.length" class="muted">没有符合条件的凭证。</p>
    </template>
  </section>
</template>

<style scoped>
.export-setup-table .grid { min-width: 500px; }
.export-cols { display: flex; flex-wrap: wrap; gap: 6px; margin-block: 10px; }
.voucher-period-row { border: 0; margin: 0; min-width: 0; display: flex; gap: 14px; align-items: center; flex-wrap: wrap; padding: 10px 0; }
.voucher__lines input { border-color: transparent; background: transparent; min-height: 30px; width: 100%; }
.voucher__lines input:hover, .voucher__lines input:focus { border-color: var(--line-strong); background: var(--surface); }
.voucher__lines tfoot { background: var(--surface-2); }
</style>
