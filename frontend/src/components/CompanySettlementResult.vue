<script setup lang="ts">
import { computed, inject, reactive } from "vue";
import type { CompareResult } from "../api/types";
import { COMPARE_FOCUS } from "../compareFocus";
import { money } from "../format";

const props = defineProps<{ result: CompareResult }>();
const showSource = inject(COMPARE_FOCUS, () => undefined);
const EMPTY = { a: [] as string[], b: [] as string[] };
const verb = computed(() => (props.result.side === "receivable" ? "收款" : "付款"));
const REASONS: Record<string, string> = {
  no_party: "不是发票上的往来单位",
  no_name: "对账单没有户名",
  own_account: "本公司账户",
  ambiguous_name: "户名对应不止一个单位",
};
const open = reactive(new Set<string>());

function toggle(name: string): void {
  if (open.has(name)) open.delete(name);
  else open.add(name);
}
</script>

<template>
  <div>
    <table v-if="result.parties?.length" class="grid ledger" aria-label="往来单位">
      <thead>
        <tr>
          <th>往来单位</th><th class="num">期初</th><th class="num">本期发票</th><th class="num">本期{{ verb }}</th>
          <th class="num">期末余额</th><th class="num">未对上发票</th><th class="num">未逐笔对应流水</th><th></th>
        </tr>
      </thead>
      <tbody>
        <template v-for="party in result.parties" :key="party.name">
          <tr>
            <th scope="row">
              <button type="button" class="link" :title="`${party.name}：期初、本期发票与收付款的来源`"
                      @click="showSource({ label: party.name, record_ids: party.record_ids ?? EMPTY, steps: party.steps ?? [] })">{{ party.name }}</button>
            </th>
            <td class="num">{{ money(party.opening) }}</td>
            <td class="num">{{ money(party.invoiced) }}</td>
            <td class="num">{{ money(party.settled) }}</td>
            <td class="num">{{ money(party.closing) }}</td>
            <td class="num">{{ party.unpaid.length }}</td>
            <td class="num">{{ party.unallocated.length }}</td>
            <td class="nowrap">
              <button v-if="party.unpaid.length || party.unallocated.length" type="button" class="link"
                      :aria-expanded="open.has(party.name)" @click="toggle(party.name)">明细</button>
            </td>
          </tr>
          <tr v-if="open.has(party.name)" class="row--detail">
            <td colspan="8">
              <table v-if="party.unpaid.length" class="grid" :aria-label="`${party.name} 未对上发票`">
                <caption>未对上{{ verb }}的发票</caption>
                <thead><tr><th>发票号码</th><th>开票日期</th><th class="num">价税合计</th></tr></thead>
                <tbody>
                  <tr v-for="item in party.unpaid" :key="item.invoice_number">
                    <td>{{ item.invoice_number }}</td><td class="nowrap">{{ item.invoice_date }}</td><td class="num">{{ money(item.total) }}</td>
                  </tr>
                </tbody>
              </table>
              <!-- Not tied to invoices on purpose: partial payments and prepayments are not guessed. -->
              <table v-if="party.unallocated.length" class="grid" :aria-label="`${party.name} 未逐笔对应流水`">
                <caption>未逐笔对应的流水（部分{{ verb }}、预付或退款）</caption>
                <thead><tr><th>日期</th><th>对账单户名</th><th>摘要</th><th class="num">金额</th></tr></thead>
                <tbody>
                  <tr v-for="item in party.unallocated" :key="item.row_id">
                    <td class="nowrap">{{ item.date }}</td><td>{{ item.counterparty }}</td><td>{{ item.details }}</td><td class="num">{{ money(item.amount) }}</td>
                  </tr>
                </tbody>
              </table>
            </td>
          </tr>
        </template>
      </tbody>
      <tfoot v-if="result.totals">
        <tr>
          <th scope="row">合计</th>
          <td class="num">{{ money(result.totals.opening) }}</td>
          <td class="num">{{ money(result.totals.invoiced) }}</td>
          <td class="num">{{ money(result.totals.settled) }}</td>
          <td class="num">{{ money(result.totals.closing) }}</td>
          <td colspan="3"></td>
        </tr>
      </tfoot>
    </table>

    <section v-if="result.matches?.length" class="panel" aria-label="逐笔对应">
      <h3>逐笔对应（{{ result.matches.length }} 笔流水）</h3>
      <table class="grid">
        <thead><tr><th>日期</th><th>对账单户名</th><th class="num">金额</th><th>发票</th><th>依据</th></tr></thead>
        <tbody>
          <tr v-for="item in result.matches" :key="item.flow.row_id">
            <td class="nowrap">{{ item.flow.date }}</td>
            <td>{{ item.flow.counterparty }}<span v-if="item.flow.name_match === 'prefix'" class="muted">（户名截断）</span></td>
            <td class="num">{{ money(item.flow.amount) }}</td>
            <td>{{ item.invoices.map((inv) => `${inv.invoice_number}（${money(inv.total)}）`).join("、") }}</td>
            <td class="nowrap">
              {{ item.basis }}
              <button type="button" class="link" @click="showSource({
                label: `${item.flow.date} ${item.flow.counterparty} ${money(item.flow.amount)}`,
                record_ids: item.record_ids ?? EMPTY,
                steps: [`${item.basis}：流水 ${money(item.flow.amount)} = ${item.invoices.map((inv) => money(inv.total)).join(' + ')}`],
              })">来源</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="result.red_offsets?.length || result.red_unmatched?.length" class="panel" aria-label="红字发票">
      <h3>红字发票</h3>
      <ul class="warnings warnings--compact">
        <li v-for="item in result.red_offsets" :key="item.red.invoice_number">
          {{ item.red.invoice_number }}（{{ money(item.red.total) }}）冲销 {{ item.blue.invoice_number }}
        </li>
        <li v-for="item in result.red_unmatched" :key="item.invoice_number" class="check--failed">
          {{ item.invoice_number }}（{{ money(item.total) }}）没有找到同额原票，只冲减余额
        </li>
      </ul>
    </section>

    <section v-if="result.ambiguous_flows?.length" class="panel" aria-label="户名不唯一">
      <h3>户名对应不止一个往来单位（{{ result.ambiguous_flows.length }} 笔，未归属）</h3>
      <table class="grid">
        <thead><tr><th>日期</th><th>对账单户名</th><th class="num">金额</th></tr></thead>
        <tbody>
          <tr v-for="item in result.ambiguous_flows" :key="item.row_id">
            <td class="nowrap">{{ item.date }}</td><td>{{ item.counterparty }}</td><td class="num">{{ money(item.amount) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <details v-if="result.non_invoice_flows?.length" class="panel" aria-label="非发票流水">
      <summary><strong>非发票流水（{{ result.non_invoice_flows.length }} 笔：手续费、税费、工资、借款、本公司账户等）</strong></summary>
      <table class="grid">
        <thead><tr><th>日期</th><th>对账单户名</th><th>摘要</th><th class="num">金额</th><th>原因</th></tr></thead>
        <tbody>
          <tr v-for="item in result.non_invoice_flows" :key="item.row_id">
            <td class="nowrap">{{ item.date }}</td><td>{{ item.counterparty || "—" }}</td><td>{{ item.details }}</td>
            <td class="num">{{ money(item.amount) }}</td><td class="nowrap">{{ REASONS[item.reason ?? ""] ?? item.reason }}</td>
          </tr>
        </tbody>
      </table>
    </details>

    <p v-if="result.excluded_invoices?.length" class="muted">
      {{ result.excluded_invoices.length }} 张发票金额、日期或对方名称未识别，未参与核对：{{ result.excluded_invoices.map((item) => item.invoice_number || item.source_files.join("、")).join("；") }}
    </p>
  </div>
</template>
