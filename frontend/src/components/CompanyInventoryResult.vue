<script setup lang="ts">
import { reactive } from "vue";
import type { CompareResult } from "../api/types";
import { money } from "../format";

defineProps<{ result: CompareResult }>();
// Stock is per category (the books' 库存商品 detail); specs drop down under it as rows in the same columns.
// Monthly rows open as a full-width row under the item; a nested table in one cell gets clipped.
const specsOpen = reactive(new Set<string>());
const monthsOpen = reactive(new Set<string>());

function toggle(set: Set<string>, key: string): void {
  if (set.has(key)) set.delete(key);
  else set.add(key);
}
</script>

<template>
  <div>
    <p v-if="result.items?.length" class="muted">进货成本口径：{{ result.cost_label }}；单价为品类月末一次加权平均，规格只细分购销数量。</p>
    <table v-if="result.items?.length" class="grid ledger" aria-label="进销存">
      <thead>
        <tr>
          <th>品类</th><th>单位</th>
          <th class="num">期初数量</th><th class="num">期初金额</th><th class="num">购入数量</th><th class="num">购入金额</th>
          <th class="num">销售数量</th><th class="num">销售成本</th><th class="num">期末数量</th><th class="num">期末金额</th><th>说明</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="item in result.items" :key="item.key">
          <tr :class="{ 'row--failed': item.oversold }">
            <th scope="row" class="nowrap">
              <button
                v-if="item.specs.length"
                type="button"
                class="link chevron"
                :aria-expanded="specsOpen.has(item.key)"
                :aria-label="`${item.name} 的 ${item.specs.length} 个规格`"
                @click="toggle(specsOpen, item.key)"
              >{{ specsOpen.has(item.key) ? "▾" : "▸" }}</button>
              {{ item.name }}
              <span v-if="item.account_code" class="muted" :title="`库存商品明细科目 ${item.account_code}`">{{ item.account_code }}</span>
            </th>
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
              <!-- Selling more than is in stock is shown, never evened out: the gap is missing invoices or opening stock. -->
              <span v-if="item.sold_never_bought" class="tag tag--danger">进项和期初中没有</span>
              <span v-else-if="item.oversold" class="tag tag--danger">卖超</span>
              <button type="button" class="link" :aria-expanded="monthsOpen.has(item.key)" @click="toggle(monthsOpen, item.key)">逐月</button>
            </td>
          </tr>
          <template v-if="specsOpen.has(item.key)">
            <tr v-for="spec in item.specs" :key="spec.key" class="row--spec">
              <!-- The standard name repeats only when it differs from the category (e.g. a catalog name under 螺纹钢). -->
              <td class="spec-name"><template v-if="spec.name !== item.name">{{ spec.name }} </template>{{ spec.spec || "（无规格）" }}</td>
              <td class="nowrap">{{ spec.unit }}</td>
              <td class="num muted" colspan="2" title="期初只在品类上，不分摊到规格">—</td>
              <td class="num">{{ spec.in_qty }}</td>
              <td class="num">{{ money(spec.in_amount) }}</td>
              <td class="num">{{ spec.out_qty }}</td>
              <td class="num muted" title="成本按品类加权平均结转，不分摊到规格">—</td>
              <td class="num" title="购入 − 销售，不含期初">净 {{ spec.net_qty }}</td>
              <td class="num muted">—</td>
              <td></td>
            </tr>
          </template>
          <tr v-if="monthsOpen.has(item.key)" class="row--detail">
            <td colspan="11">
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
          <th scope="row" colspan="3">合计</th>
          <td class="num">{{ money(result.totals.open_amount) }}</td>
          <td></td>
          <td class="num">{{ money(result.totals.in_amount) }}</td>
          <td></td>
          <td class="num">{{ money(result.totals.cost) }}</td>
          <td></td>
          <td class="num">{{ money(result.totals.end_amount) }}</td>
          <td></td>
        </tr>
      </tfoot>
    </table>

    <section v-if="result.opening?.unassigned.length" class="panel" aria-label="未计入期初的账套明细">
      <h3>未计入期初的账套明细（{{ result.opening.unassigned.length }} 个）</h3>
      <table class="grid">
        <thead><tr><th>科目</th><th class="num">数量</th><th class="num">金额</th><th>原因</th></tr></thead>
        <tbody>
          <tr v-for="entry in result.opening.unassigned" :key="entry.code">
            <td>{{ entry.code }} {{ entry.account }}</td><td class="num">{{ entry.qty }} {{ entry.unit }}</td>
            <td class="num">{{ money(entry.amount) }}</td><td>{{ entry.reason }}</td>
          </tr>
        </tbody>
      </table>
    </section>

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
