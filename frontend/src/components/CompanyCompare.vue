<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { request } from "../api/client";
import type { Company, CompareResult } from "../api/types";
import { errorText, money } from "../format";

const props = defineProps<{ company: Company }>();
// Folder pairs with a reconciliation relation; the backend refuses any other pair.
const RELATIONS = [
  { id: "deduction", label: "成本发票 ⇄ 进项抵扣（勾选清单）", a: "cost_invoice_dir", b: "input_deduction_dir" },
] as const;
const TIMING: Record<string, string> = {
  current: "当期开票当期勾选",
  carried: "前期开票本期勾选",
  after_period: "开票晚于所属期",
  unknown: "开票日期未识别",
};

const filters = reactive({ relation: RELATIONS[0].id as string, start: "", end: "" });
const result = ref<CompareResult | null>(null);
const loading = ref(false);
const error = ref("");
const relation = computed(() => RELATIONS.find((item) => item.id === filters.relation) ?? RELATIONS[0]);
const unlistedSpecial = computed(() => result.value?.not_listed?.special ?? []);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams({ a: relation.value.a, b: relation.value.b });
  if (filters.start) query.set("start", filters.start);
  if (filters.end) query.set("end", filters.end);
  try {
    result.value = await request<CompareResult>(`/api/v1/companies/${encodeURIComponent(props.company.id)}/compare?${query}`);
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.company.id,
  () => {
    result.value = null;
    void load();
  },
  { immediate: true },
);
</script>

<template>
  <section aria-label="勾稽">
    <form class="toolbar" @submit.prevent="load">
      <select v-model="filters.relation" aria-label="比较关系">
        <option v-for="item in RELATIONS" :key="item.id" :value="item.id">{{ item.label }}</option>
      </select>
      <input v-model="filters.start" type="month" aria-label="开始月份">
      <span class="muted">至</span>
      <input v-model="filters.end" type="month" aria-label="结束月份">
      <button type="submit" :disabled="loading" :aria-busy="loading">{{ loading ? "核对中…" : "核对" }}</button>
    </form>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

    <template v-if="result">
      <p v-if="result.state !== 'ok'" class="banner" :class="result.state === 'unreadable' ? 'banner--error' : 'banner--note'" role="status">
        {{ result.message }}
      </p>
      <template v-if="result.state === 'ok' || result.state === 'no_lists'">
        <p v-if="result.basis_label" class="banner banner--note">{{ result.basis_label }}</p>
        <details class="checks" :class="{ 'checks--failed': !result.checks_ok }" :open="!result.checks_ok" role="status">
          <summary><strong>{{ result.checks_ok ? `核对校验全部成立（${result.checks?.length ?? 0} 项）` : "核对校验不成立" }}</strong></summary>
          <ul>
            <li v-for="check in result.checks" :key="check.code" :class="{ 'check--failed': !check.ok }">
              {{ check.ok ? "✓" : "✗" }} {{ check.message }}
            </li>
          </ul>
        </details>
        <ul v-if="result.warnings?.length" class="warnings warnings--compact">
          <li v-for="warning in result.warnings" :key="warning.code">{{ warning.message }}</li>
        </ul>

        <table v-if="result.periods?.length" class="grid ledger" aria-label="各所属期">
          <thead>
            <tr>
              <th>所属期</th><th class="num">清单行数</th><th class="num">当期开票</th><th class="num">前期开票</th>
              <th class="num">其它</th><th class="num">目录无原票</th><th class="num">未勾选</th><th class="num">有效抵扣税额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in result.periods" :key="row.period">
              <th scope="row" class="nowrap">{{ row.period }}</th>
              <td class="num">{{ row.list_rows }}</td>
              <td class="num">{{ row.matched_current }}</td>
              <td class="num">{{ row.matched_carried }}</td>
              <td class="num">{{ row.matched_other }}</td>
              <td class="num" :class="{ 'check--failed': row.list_only }">{{ row.list_only }}</td>
              <td class="num">{{ row.not_selected }}</td>
              <td class="num">{{ money(row.deductible_tax) }}</td>
            </tr>
          </tbody>
        </table>

        <section v-if="result.list_only?.length" class="panel" aria-label="清单有、目录无">
          <h3>清单有、目录无（{{ result.list_only.length }} 张，缺原始发票）</h3>
          <table class="grid">
            <thead><tr><th>所属期</th><th>发票号码</th><th>开票日期</th><th>销售方</th><th class="num">税额</th><th>清单文件</th></tr></thead>
            <tbody>
              <tr v-for="item in result.list_only" :key="item.period + item.invoice_number">
                <td class="nowrap">{{ item.period }}</td><td>{{ item.invoice_number }}</td><td class="nowrap">{{ item.invoice_date }}</td>
                <td>{{ item.seller }}</td><td class="num">{{ money(item.税额) }}</td><td class="path">{{ item.file }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section v-if="result.matched?.length" class="panel" aria-label="已勾选并对上的发票">
          <h3>已勾选并对上（{{ result.matched.length }} 张）</h3>
          <table class="grid">
            <thead><tr><th>所属期</th><th>发票号码</th><th>开票月</th><th>情况</th><th>销售方</th><th class="num">清单税额</th><th class="num">发票税额</th></tr></thead>
            <tbody>
              <tr v-for="item in result.matched" :key="item.period + item.invoice_number" :class="{ 'row--failed': !item.tax_ok }">
                <td class="nowrap">{{ item.period }}</td><td>{{ item.invoice_number }}</td><td class="nowrap">{{ item.invoice_month ?? "—" }}</td>
                <td class="nowrap">{{ TIMING[item.timing] }}</td><td>{{ item.seller }}</td>
                <td class="num">{{ money(item.税额) }}</td><td class="num">{{ money(item.invoice_tax) }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section v-if="unlistedSpecial.length || result.not_listed?.unknown_type.length" class="panel" aria-label="目录有、清单无">
          <h3>目录有、未出现在清单（专票 {{ unlistedSpecial.length }} 张；普票 {{ result.not_listed?.ordinary ?? 0 }} 张不能抵扣，未列出）</h3>
          <table class="grid">
            <thead><tr><th>发票号码</th><th>开票日期</th><th>票种</th><th>销售方</th><th class="num">税额</th><th>之后的清单</th></tr></thead>
            <tbody>
              <tr v-for="item in [...unlistedSpecial, ...(result.not_listed?.unknown_type ?? [])]" :key="item.invoice_number">
                <td>{{ item.invoice_number }}</td><td class="nowrap">{{ item.invoice_date }}</td>
                <td class="nowrap">{{ item.invoice_type || "未识别" }}</td><td>{{ item.seller }}</td>
                <td class="num">{{ money(item.tax) }}</td>
                <!-- With a list for this month or later, “not in it” means not selected yet; without one it is unknown. -->
                <td class="nowrap">{{ item.later_list_periods.length ? `${item.later_list_periods.join("、")} 未勾选` : "还没有清单" }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <p v-if="result.duplicates?.length" class="banner banner--error" role="alert">
          重复勾选：{{ result.duplicates.map((item) => `${item.invoice_number}（${item.periods.join("、")}）`).join("；") }}
        </p>
        <p v-if="result.unrecognized?.length" class="muted">
          未识别的文件：{{ result.unrecognized.map((item) => `${item.file}（${item.message}）`).join("；") }}
        </p>
      </template>
    </template>
  </section>
</template>
