<script setup lang="ts">
import { computed, ref } from "vue";
import type { BankLedger } from "../api/types";
import { money } from "../format";

const props = defineProps<{ bank: BankLedger }>();
const filterText = ref("");
const issues = computed(() => props.bank.issues ?? []);
const accounts = computed(() => {
  const tokens = filterText.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const list = props.bank.accounts ?? [];
  if (!tokens.length) return list;
  return list
    .map((account) => {
      const accountHaystack = `${account.label} ${account.account_name} ${account.account_no} ${account.bank_name}`.toLocaleLowerCase();
      if (tokens.every((tok) => accountHaystack.includes(tok))) return account;
      const matchedPeriods = account.periods.filter((row) =>
        tokens.every((tok) => `${accountHaystack} ${row.period} ${row.inflow} ${row.outflow} ${row.closing ?? ""}`.toLocaleLowerCase().includes(tok)),
      );
      return matchedPeriods.length ? { ...account, periods: matchedPeriods } : null;
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);
});

function state(row: { ok: boolean; missing_months: string[] }): string {
  if (row.missing_months.length) return `缺 ${row.missing_months.join("、")} 对账单`;
  return row.ok ? "✓" : "期初 + 收入 − 支出 ≠ 期末";
}
</script>

<template>
  <section class="panel" aria-label="银行流水">
    <h3>银行流水</h3>
    <p v-if="bank.state !== 'ok'" class="banner" :class="bank.state === 'unreadable' ? 'banner--error' : 'banner--note'" role="status">
      {{ bank.message }}
      <template v-if="bank.sources?.receipts">（目录里有 {{ bank.sources.receipts }} 份回单，汇总只读对账单。）</template>
    </p>
    <template v-if="bank.state === 'ok'">
      <p class="banner banner--note">{{ bank.basis_label }}</p>
      <!-- Same rule as the invoice checks: computed by the backend, red when any fails, open then. -->
      <details class="checks" :class="{ 'checks--failed': !bank.checks_ok }" :open="!bank.checks_ok" role="status">
        <summary><strong>{{ bank.checks_ok ? `余额校验全部成立（${bank.checks?.length ?? 0} 项）` : "余额校验不成立，缺月或对账单有误" }}</strong></summary>
        <ul>
          <li v-for="check in bank.checks" :key="check.code" :class="{ 'check--failed': !check.ok }">
            {{ check.ok ? "✓" : "✗" }} {{ check.message }}
          </li>
        </ul>
      </details>
      <ul v-if="issues.length" class="warnings warnings--compact" aria-label="对账单问题">
        <li v-for="issue in issues" :key="issue.code + issue.message" :class="{ 'check--failed': issue.level === '错误' }">
          {{ issue.level }}：{{ issue.message }}
        </li>
      </ul>

      <div class="toolbar">
        <input v-model="filterText" type="search" aria-label="筛选银行账户或期间" placeholder="按银行名 / 账号 / 期间 / 金额筛选…">
        <button v-if="filterText.trim()" type="button" class="ghost" @click="filterText = ''">清除</button>
      </div>
      <p v-if="!accounts.length && filterText.trim()" class="muted">没有匹配「{{ filterText.trim() }}」的银行账户或期间。</p>
      <table v-for="account in accounts" :key="account.account_no" class="grid ledger" :aria-label="account.label">
        <caption>{{ account.label }} · <span class="muted">{{ account.account_name }}，对账单 <span class="nowrap">{{ account.first_month }} 至 {{ account.last_month }}</span></span></caption>
        <thead>
          <tr>
            <th>期间</th><th class="num">期初余额</th><th class="num">收入</th><th class="num">支出</th>
            <th class="num">期末余额</th><th class="num">笔数</th><th>校验</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in account.periods" :key="row.period" :class="{ 'row--failed': !row.ok }">
            <th scope="row" class="nowrap">{{ row.period }}</th>
            <td class="num">{{ money(row.opening) }}</td>
            <td class="num">{{ money(row.inflow) }}</td>
            <td class="num">{{ money(row.outflow) }}</td>
            <td class="num">{{ money(row.closing) }}</td>
            <td class="num">{{ row.rows }}</td>
            <td class="nowrap">{{ state(row) }}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">合计</th>
            <td class="num">{{ money(account.totals.opening) }}</td>
            <td class="num">{{ money(account.totals.inflow) }}</td>
            <td class="num">{{ money(account.totals.outflow) }}</td>
            <td class="num">{{ money(account.totals.closing) }}</td>
            <td class="num">{{ account.totals.rows }}</td>
            <td class="nowrap">{{ state(account.totals) }}</td>
          </tr>
        </tfoot>
      </table>
      <p class="muted">
        对账单 {{ bank.sources?.statements ?? 0 }} 份、回单 {{ bank.sources?.receipts ?? 0 }} 份（回单不参与汇总）<template v-if="bank.sources?.unrecognized.length">；未识别 {{ bank.sources.unrecognized.length }} 份：{{ bank.sources.unrecognized.map((item) => item.file).join("、") }}</template>。
      </p>
    </template>
  </section>
</template>
