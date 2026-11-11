<script setup lang="ts">
import { computed, inject } from "vue";
import { COMPARE_FOCUS } from "../compareFocus";
import type { CompareResult } from "../api/types";
import { money } from "../format";

const props = defineProps<{ result: CompareResult }>();
const showSource = inject(COMPARE_FOCUS, () => undefined);
const TIMING: Record<string, string> = {
  current: "当期开票当期勾选",
  carried: "前期开票本期勾选",
  after_period: "开票晚于所属期",
  unknown: "开票日期未识别",
};
const unlistedSpecial = computed(() => props.result.not_listed?.special ?? []);
const unlisted = computed(() => [...unlistedSpecial.value, ...(props.result.not_listed?.unknown_type ?? [])]);
</script>

<template>
  <div>
    <table v-if="result.periods?.length" class="grid ledger" aria-label="各所属期">
      <thead>
        <tr>
          <th>所属期</th><th class="num">清单行数</th><th class="num">当期开票</th><th class="num">前期开票</th>
          <th class="num">其它</th><th class="num">目录无原票</th><th class="num">未勾选</th><th class="num">有效抵扣税额</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in result.periods" :key="row.period">
          <th scope="row" class="nowrap">
            <button type="button" class="link" @click="showSource({ label: `所属期 ${row.period}`, record_ids: row.record_ids ?? { a: [], b: [] }, steps: row.steps ?? [] })">{{ row.period }}</button>
          </th>
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

    <section v-if="unlisted.length" class="panel" aria-label="目录有、清单无">
      <h3>目录有、未出现在清单（专票 {{ unlistedSpecial.length }} 张；普票 {{ result.not_listed?.ordinary ?? 0 }} 张不能抵扣，未列出）</h3>
      <table class="grid">
        <thead><tr><th>发票号码</th><th>开票日期</th><th>票种</th><th>销售方</th><th class="num">税额</th><th>之后的清单</th></tr></thead>
        <tbody>
          <tr v-for="item in unlisted" :key="item.invoice_number">
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
  </div>
</template>
