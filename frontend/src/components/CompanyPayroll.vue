<script setup lang="ts">
import { companySourceKey } from "../stores/companies";
import { computed, reactive, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company } from "../api/types";
import { errorText, money } from "../format";

// 工资社保 (WS-05 stage 3), laid out like the tax bureau's 社保费应缴明细. The backend parses the
// company's 工资社保 folder (Excel / text PDF; images are listed, not read) and computes every check;
// nothing is written until a month is confirmed into 申报数据.json, which the voucher draft accrues from.
interface Side { count: number | null; wage: string | null; base: string | null; rate: string | null; due: string | null }
interface Check { code: string; ok: boolean; message: string }
interface PayrollRow { insurance: string; total: string | null; unit: Side; personal: Side; checks: Check[] }
interface PayrollMonth { month: string; source: string; rows: PayrollRow[]; unit_total: string; personal_total: string; total: string; checks_ok: boolean }
interface PayrollPayload {
  folder: string; folder_present: boolean; tax_file: boolean; tax_revision: string | null; people_masked: boolean;
  files: { file: string; kind: string; status: string; message: string }[];
  months: PayrollMonth[];
  confirmed: Record<string, { 单位部分: string | null; 个人部分: string | null; 来源: string }>;
  people: { name: string; id_number: string; base: string | null; month: string | null }[];
}
type Field = "count" | "wage" | "base" | "rate" | "due";

const props = defineProps<{ company: Company }>();
const FIELDS: { key: Field; label: string }[] = [
  { key: "count", label: "缴费人数" }, { key: "wage", label: "缴费工资" }, { key: "base", label: "缴费基数" },
  { key: "rate", label: "费率" }, { key: "due", label: "应缴费额（元）" },
];
const INSURANCES = ["城镇职工基本养老保险", "失业保险", "工伤保险", "职工基本医疗保险", "大额医疗费用补助"];
const base = computed(() => `/api/v1/companies/${encodeURIComponent(props.company.id)}/payroll`);
const payload = ref<PayrollPayload | null>(null);
const error = ref("");
const notice = ref("");
const loading = ref(false);
const saving = ref(false);
const reveal = ref(false);
// Hand entry for a month without a readable file, in the same layout.
const manual = ref<{ month: string; rows: { insurance: string; unit: Record<Field, string>; personal: Record<Field, string> }[] } | null>(null);

const blank = (): Record<Field, string> => ({ count: "", wage: "", base: "", rate: "", due: "" });
const cell = (value: string | number | null) => (value === null || value === "" ? "--" : typeof value === "number" ? String(value) : value);
const amount = (value: string | null) => (value === null ? "--" : money(value));

let loadGeneration = 0;
async function load(): Promise<void> {
  const mine = ++loadGeneration;
  loading.value = true;
  error.value = "";
  try {
    const next = await request<PayrollPayload>(`${base.value}${reveal.value ? "?reveal=true" : ""}`, { timeoutMs: 60_000 });
    if (mine !== loadGeneration) return;
    payload.value = next;
  } catch (cause) {
    if (mine === loadGeneration) error.value = errorText(cause);
  } finally {
    if (mine === loadGeneration) loading.value = false;
  }
}

async function save(months: Record<string, unknown>, done: string): Promise<void> {
  if (!payload.value) return;
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    await request(base.value, { method: "PUT", body: { revision: payload.value.tax_revision, months } });
    notice.value = done;
    manual.value = null;
    await load();
  } catch (cause) {
    if (cause instanceof ApiError && cause.code === "PAYROLL_CONFLICT") {
      await load();
      error.value = "申报数据.json 已在别处修改，已刷新，请重新确认。";
    } else {
      error.value = errorText(cause);
    }
  } finally {
    saving.value = false;
  }
}

function confirmMonth(item: PayrollMonth): Promise<void> {
  return save({ [item.month]: { rows: item.rows, source: item.source } },
    `已确认 ${item.month} 社保：单位 ${money(item.unit_total)}、个人 ${money(item.personal_total)}，写入 申报数据.json；重新生成草稿后计提。`);
}

function removeMonth(month: string): Promise<void> {
  return save({ [month]: null }, `已取消 ${month} 的社保确认；重新生成草稿后不再计提。`);
}

function startManual(): void {
  manual.value = { month: "", rows: INSURANCES.map((insurance) => ({ insurance, unit: blank(), personal: blank() })) };
}

function saveManual(): Promise<void> {
  const entry = manual.value!;
  const rows = entry.rows
    .filter((row) => row.unit.due || row.personal.due)
    .map((row) => ({ insurance: row.insurance, total: null, unit: { ...row.unit }, personal: { ...row.personal } }));
  return save({ [entry.month]: { rows, source: "手工录入" } }, `已录入并确认 ${entry.month} 社保，写入 申报数据.json。`);
}

watch(reveal, () => void load());
watch(() => companySourceKey(props.company, ["payroll_social_dir"]), (_value, previous) => {
  payload.value = null;
  if (previous === undefined || JSON.parse(previous)[0] !== props.company.id) manual.value = null;
  void load();
}, { immediate: true });
</script>

<template>
  <section aria-label="工资社保">
    <div class="toolbar">
      <button type="button" :disabled="loading" :aria-busy="loading" @click="load">{{ loading ? "读取中…" : "重新读取" }}</button>
      <button type="button" :disabled="!payload?.tax_file || !!manual" @click="startManual">手工录入一个月…</button>
      <label v-if="payload?.people.length" class="nowrap"><input v-model="reveal" type="checkbox"> 显示完整姓名与证件号</label>
    </div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <template v-if="payload">
      <p class="banner banner--note">
        读取公司资料夹 {{ payload.folder || "工资社保" }}/ 里电子税务局导出的“社保费应缴明细”（Excel 或有文字层的 PDF）。确认后写入 申报数据.json，
        凭证草稿据此计提：借 管理费用（单位部分）、借 应付职工薪酬—工资（个人部分），贷 应付社会保险费。
      </p>
      <p v-if="!payload.folder_present" class="muted">没有找到工资社保子目录，可以手工录入。</p>
      <p v-if="!payload.tax_file" class="banner banner--note">还没有 申报数据.json：先在“凭证草稿”生成一次草稿（会写出模板），再确认社保。</p>
      <ul v-if="payload.files.some((file) => file.status !== 'parsed')" class="warnings warnings--compact">
        <li v-for="file in payload.files.filter((item) => item.status !== 'parsed')" :key="file.file">{{ file.file }}：{{ file.message || "不是社保明细文件，已跳过" }}</li>
      </ul>

      <article v-for="item in payload.months" :key="item.month" class="panel" :aria-label="`${item.month} 社保费应缴明细`">
        <header class="voucher__head">
          <strong>{{ item.month }} 社保费应缴明细</strong>
          <span class="muted">来源：{{ item.source }}</span>
          <span :class="item.checks_ok ? 'muted' : 'check--failed'">单位 {{ money(item.unit_total) }} · 个人 {{ money(item.personal_total) }} · 合计 {{ money(item.total) }}</span>
          <span v-if="payload.confirmed[item.month]" class="tag tag--accent">已确认</span>
        </header>
        <div class="payroll__scroll">
          <table class="grid payroll">
            <thead>
              <tr>
                <th rowspan="2">费款所属期</th><th rowspan="2">险种</th><th rowspan="2" class="num">应缴费额合计</th>
                <th colspan="5" class="payroll__group">单位部分</th><th colspan="5" class="payroll__group">个人部分</th>
              </tr>
              <tr>
                <th v-for="field in FIELDS" :key="`u-${field.key}`" class="num">{{ field.label }}</th>
                <th v-for="field in FIELDS" :key="`p-${field.key}`" class="num">{{ field.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in item.rows" :key="row.insurance" :class="{ 'row--failed': row.checks.some((check) => !check.ok) }">
                <td>{{ item.month }}</td>
                <td>{{ row.insurance }}</td>
                <td class="num">{{ amount(row.total) }}</td>
                <td v-for="field in FIELDS" :key="`u-${field.key}`" class="num">{{ field.key === "due" || field.key === "wage" || field.key === "base" ? amount(row.unit[field.key] as string | null) : cell(row.unit[field.key]) }}</td>
                <td v-for="field in FIELDS" :key="`p-${field.key}`" class="num">{{ field.key === "due" || field.key === "wage" || field.key === "base" ? amount(row.personal[field.key] as string | null) : cell(row.personal[field.key]) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <details class="checks" :class="{ 'checks--failed': !item.checks_ok }" :open="!item.checks_ok">
          <summary>{{ item.checks_ok ? "核对全部成立" : "核对不成立" }}</summary>
          <ul><li v-for="check in item.rows.flatMap((row) => row.checks)" :key="check.message" :class="{ 'check--failed': !check.ok }">{{ check.ok ? "✓" : "✗" }} {{ check.message }}</li></ul>
        </details>
        <div class="toolbar">
          <button type="button" class="primary" :disabled="saving || !payload.tax_file" @click="confirmMonth(item)">
            {{ payload.confirmed[item.month] ? "重新确认" : "确认写入申报数据" }}
          </button>
          <button v-if="payload.confirmed[item.month]" type="button" :disabled="saving" @click="removeMonth(item.month)">取消确认</button>
          <span v-if="!item.checks_ok" class="check--failed">核对不成立时请先核对原表；确认后按表中应缴费额计提。</span>
        </div>
      </article>
      <p v-if="!payload.months.length && !manual" class="muted">还没有可显示的社保明细。</p>

      <section v-if="payload.people.length" class="panel" aria-label="人员明细">
        <h3>人员明细 <span class="muted">{{ payload.people_masked ? "（已脱敏）" : "（完整信息，仅本机显示）" }}</span></h3>
        <table class="grid">
          <thead><tr><th>姓名</th><th>证件号码</th><th class="num">缴费基数</th><th>所属期</th></tr></thead>
          <tbody><tr v-for="(person, index) in payload.people" :key="index"><td>{{ person.name }}</td><td>{{ person.id_number }}</td><td class="num">{{ amount(person.base) }}</td><td>{{ person.month || "—" }}</td></tr></tbody>
        </table>
      </section>

      <section v-if="manual" class="panel" aria-label="手工录入社保">
        <div class="toolbar"><label class="nowrap">费款所属期 <input v-model="manual.month" type="month" aria-label="费款所属期"></label></div>
        <div class="payroll__scroll">
          <table class="grid payroll">
            <thead>
              <tr><th rowspan="2">险种</th><th colspan="5" class="payroll__group">单位部分</th><th colspan="5" class="payroll__group">个人部分</th></tr>
              <tr><th v-for="field in FIELDS" :key="`mu-${field.key}`">{{ field.label }}</th><th v-for="field in FIELDS" :key="`mp-${field.key}`">{{ field.label }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in manual.rows" :key="row.insurance">
                <td>{{ row.insurance }}</td>
                <td v-for="field in FIELDS" :key="`mu-${field.key}`"><input v-model="row.unit[field.key]" class="payroll__input" :aria-label="`${row.insurance} 单位${field.label}`"></td>
                <td v-for="field in FIELDS" :key="`mp-${field.key}`"><input v-model="row.personal[field.key]" class="payroll__input" :aria-label="`${row.insurance} 个人${field.label}`"></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="toolbar">
          <button type="button" class="primary" :disabled="saving || !manual.month || !manual.rows.some((row) => row.unit.due || row.personal.due)" @click="saveManual">保存并确认</button>
          <button type="button" :disabled="saving" @click="manual = null">取消</button>
          <span class="muted">费率可写 16% 或 0.16；没有的项留空。</span>
        </div>
      </section>
    </template>
  </section>
</template>
