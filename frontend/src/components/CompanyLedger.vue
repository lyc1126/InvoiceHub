<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { request } from "../api/client";
import type { Company, LedgerPayload, LedgerTotals } from "../api/types";
import CompanyBankLedger from "./CompanyBankLedger.vue";
import { errorText, money, taxpayerLabel } from "../format";

const props = defineProps<{ company: Company }>();
const filters = reactive({ granularity: "month" as LedgerPayload["granularity"], start: "", end: "" });
const ledger = ref<LedgerPayload | null>(null);
const loading = ref(false);
const error = ref("");

const REASONS: Record<string, string> = {
  amount_unrecognized: "金额未识别",
  amount_conflict: "格式间金额不一致",
  amount_inconsistent: "金额对不上",
};

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams({ granularity: filters.granularity });
  if (filters.start) query.set("start", filters.start);
  if (filters.end) query.set("end", filters.end);
  try {
    ledger.value = await request<LedgerPayload>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/ledger?${query}`);
  } catch (cause) {
    // Keep the previous result on screen; the banner says why it was not refreshed.
    error.value = errorText(cause);
  } finally {
    loading.value = false;
  }
}

function cells(totals: LedgerTotals): string[] {
  return [String(totals.count), money(totals.pretax), money(totals.tax), money(totals.total)];
}

watch(
  () => props.company.id,
  () => {
    ledger.value = null;
    void load();
  },
  { immediate: true },
);
</script>

<template>
  <section aria-label="发票账簿">
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

    <template v-if="ledger">
      <p class="banner banner--note">{{ ledger.basis_label }}</p>
      <!-- Conservation checks come from the backend; a failing one is shown in red, never hidden. -->
      <!-- Collapsed only while every check holds; any failure opens it. -->
      <details class="checks" :class="{ 'checks--failed': !ledger.checks_ok }" :open="!ledger.checks_ok" role="status">
        <summary><strong>{{ ledger.checks_ok ? `守恒校验全部成立（${ledger.checks.length} 项）` : "守恒校验不成立，结果不可用" }}</strong></summary>
        <ul>
          <li v-for="check in ledger.checks" :key="check.code" :class="{ 'check--failed': !check.ok }">
            {{ check.ok ? "✓" : "✗" }} {{ check.message }}
          </li>
        </ul>
      </details>
      <ul v-if="ledger.warnings.length" class="warnings">
        <li v-for="warning in ledger.warnings" :key="warning.code + warning.message">{{ warning.message }}</li>
      </ul>

      <table class="grid ledger">
        <thead>
          <tr>
            <th rowspan="2">期间</th>
            <th colspan="4">进项（成本发票）</th>
            <th colspan="4">销项（开具发票）</th>
            <th rowspan="2" class="num">票面差额（不含税）</th>
            <th rowspan="2">纳税人身份</th>
          </tr>
          <tr>
            <th class="num">张数</th><th class="num">不含税</th><th class="num">税额</th><th class="num">价税合计</th>
            <th class="num">张数</th><th class="num">不含税</th><th class="num">税额</th><th class="num">价税合计</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledger.periods" :key="row.period">
            <th scope="row" class="nowrap">{{ row.period }}</th>
            <td v-for="(value, index) in cells(row.input)" :key="`i${index}`" class="num">{{ value }}</td>
            <td v-for="(value, index) in cells(row.output)" :key="`o${index}`" class="num">{{ value }}</td>
            <td class="num">{{ money(row.face_difference_pretax) }}</td>
            <td>{{ row.taxpayer_types.map(taxpayerLabel).join(" / ") }}</td>
          </tr>
          <tr v-if="ledger.undated.input.count || ledger.undated.output.count" class="row--muted">
            <th scope="row" class="nowrap">日期未识别</th>
            <td v-for="(value, index) in cells(ledger.undated.input)" :key="`ui${index}`" class="num">{{ value }}</td>
            <td v-for="(value, index) in cells(ledger.undated.output)" :key="`uo${index}`" class="num">{{ value }}</td>
            <td colspan="2" class="muted">{{ filters.start || filters.end ? "限定期间时不计入合计" : "已计入合计" }}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">合计</th>
            <td v-for="(value, index) in cells(ledger.totals.input)" :key="`ti${index}`" class="num">{{ value }}</td>
            <td v-for="(value, index) in cells(ledger.totals.output)" :key="`to${index}`" class="num">{{ value }}</td>
            <td class="num">{{ money(ledger.totals.face_difference_pretax) }}</td>
            <td></td>
          </tr>
        </tfoot>
      </table>
      <p class="muted">
        同一张票的多个格式已合并（进项 {{ ledger.merged_copies.input }} 份、销项 {{ ledger.merged_copies.output }} 份）<template v-if="filters.start || filters.end">；所选期间外：进项 {{ ledger.out_of_range.input }} 张、销项 {{ ledger.out_of_range.output }} 张</template>。
      </p>

      <section v-if="ledger.excluded.length" class="panel" aria-label="未计入的发票">
        <h3>未计入的发票（{{ ledger.excluded.length }} 张）</h3>
        <table class="grid">
          <thead><tr><th>方向</th><th>发票号码</th><th>开票日期</th><th>对方</th><th>原因</th><th>文件</th></tr></thead>
          <tbody>
            <tr v-for="item in ledger.excluded" :key="item.direction + item.invoice_number + item.source_files.join()">
              <td class="nowrap">{{ item.direction === "input" ? "进项" : "销项" }}</td>
              <td>{{ item.invoice_number || "—" }}</td>
              <td class="nowrap">{{ item.invoice_date || "—" }}</td>
              <td>{{ item.counterpart || "—" }}</td>
              <td class="nowrap" :title="item.message">{{ REASONS[item.reason] }}</td>
              <td class="path">{{ item.source_files.join("、") }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <CompanyBankLedger v-if="ledger.bank" :bank="ledger.bank" />
    </template>
  </section>
</template>
