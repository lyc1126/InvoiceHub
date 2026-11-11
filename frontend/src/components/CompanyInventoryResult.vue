<script setup lang="ts">
import { reactive } from "vue";
import type { CompareResult } from "../api/types";
import { money } from "../format";

defineProps<{ result: CompareResult }>();
// Monthly rows open as a full-width row under the item; a nested table in one cell gets clipped.
const open = reactive(new Set<string>());

function toggle(key: string): void {
  if (open.has(key)) open.delete(key);
  else open.add(key);
}
</script>

<template>
  <div>
    <p v-if="result.items?.length" class="muted">进货成本口径：{{ result.cost_label }}；单价为月末一次加权平均。</p>
    <table v-if="result.items?.length" class="grid ledger" aria-label="进销存">
      <thead>
        <tr>
          <th>品目</th><th>规格</th><th>单位</th>
          <th class="num">期初数量</th><th class="num">期初金额</th><th class="num">购入数量</th><th class="num">购入金额</th>
          <th class="num">销售数量</th><th class="num">销售成本</th><th class="num">期末数量</th><th class="num">期末金额</th><th>说明</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="item in result.items" :key="item.key">
          <tr :class="{ 'row--failed': item.oversold }">
            <th scope="row">{{ item.name }}</th>
            <td class="nowrap">{{ item.spec || "—" }}</td>
            <td class="nowrap">{{ item.unit }}</td>
            <td class="num">{{ item.open_qty }}</td>
            <td class="num">{{ money(item.open_amount) }}</td>
            <td class="num">{{ item.in_qty }}</td>
            <td class="num">{{ money(item.in_amount) }}</td>
            <td class="num">{{ item.out_qty }}</td>
            <td class="num">{{ money(item.cost) }}</td>
            <td class="num">{{ item.end_qty }}</td>
            <td class="num">{{ money(item.end_amount) }}</td>
            <td class="nowrap">
              <!-- Selling more than was bought is shown, never evened out: the gap is missing invoices or opening stock. -->
              <span v-if="item.sold_never_bought" class="tag tag--danger">进项中没有</span>
              <span v-else-if="item.oversold" class="tag tag--danger">卖超</span>
              <button type="button" class="link" :aria-expanded="open.has(item.key)" @click="toggle(item.key)">逐月</button>
            </td>
          </tr>
          <tr v-if="open.has(item.key)" class="row--detail">
            <td colspan="12">
              <table class="grid" :aria-label="`${item.name} 逐月`">
                <thead><tr><th>月份</th><th class="num">期初</th><th class="num">购入</th><th class="num">销售</th><th class="num">加权单价</th><th class="num">成本</th><th class="num">期末</th><th>说明</th></tr></thead>
                <tbody>
                  <tr v-for="row in item.months" :key="row.month">
                    <td class="nowrap">{{ row.month }}</td>
                    <td class="num">{{ row.open_qty }} / {{ money(row.open_amount) }}</td>
                    <td class="num">{{ row.in_qty }} / {{ money(row.in_amount) }}</td>
                    <td class="num">{{ row.out_qty }}</td>
                    <td class="num">{{ money(row.unit_price) }}</td>
                    <td class="num">{{ money(row.cost) }}</td>
                    <td class="num">{{ row.end_qty }} / {{ money(row.end_amount) }}</td>
                    <td>{{ row.note }}</td>
                  </tr>
                </tbody>
              </table>
            </td>
          </tr>
        </template>
      </tbody>
      <tfoot v-if="result.totals">
        <tr>
          <th scope="row" colspan="6">合计</th>
          <td class="num">{{ money(result.totals.in_amount) }}</td>
          <td></td>
          <td class="num">{{ money(result.totals.cost) }}</td>
          <td></td>
          <td class="num">{{ money(result.totals.end_amount) }}</td>
          <td></td>
        </tr>
      </tfoot>
    </table>

    <section v-if="result.excluded?.length" class="panel" aria-label="未计入的明细行">
      <h3>未计入的明细行（{{ result.excluded.length }} 行）</h3>
      <table class="grid">
        <thead><tr><th>方向</th><th>发票号码</th><th>开票日期</th><th>品目</th><th>数量</th><th>原因</th><th>文件</th></tr></thead>
        <tbody>
          <tr v-for="(item, index) in result.excluded" :key="index">
            <td class="nowrap">{{ item.direction === "input" ? "进项" : "销项" }}</td>
            <td>{{ item.invoice_number || "—" }}</td><td class="nowrap">{{ item.invoice_date || "—" }}</td>
            <td>{{ item.name }} {{ item.spec }}</td><td class="num">{{ item.quantity || "—" }} {{ item.unit }}</td>
            <td class="nowrap">{{ item.reason }}</td><td class="path">{{ item.source_file }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
