<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import {
  costBase, decimalText, RULE_KIND_LABELS, RULE_SCOPE_LABELS, RULE_SOURCE_LABELS, ruleSummary,
  type CostSnapshot, type PricingRule, type RuleKind, type RuleScope, type RulesPreview, type Tier,
} from "../api/costV2";
import type { Company } from "../api/types";
import { errorText, money } from "../format";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

interface Form {
  id: string; scope: RuleScope; customer: string; item_key: string; kind: RuleKind; value: string; price_basis: "net" | "gross";
  valid_from: string; valid_to: string; rate: string; minimum: string; special: boolean;
  rounding: boolean; increment: string; ending: string; mode: "ceil" | "floor" | "half_up"; round_basis: "net" | "gross";
  tier_basis: "quantity" | "amount"; tiers: Tier[];
}
const props = defineProps<{ company: Company; snapshot: CostSnapshot | null; busy: boolean }>();
const emit = defineEmits<{ changed: []; reload: [] }>();
const draft = ref<Record<string, PricingRule>>({});
const dirty = ref(false);
const form = ref<Form | null>(null);
const formError = ref("");
const previewCustomer = ref("");
const preview = ref<{ body: Record<string, unknown>; result: RulesPreview } | null>(null);
const confirming = ref(false);
const saving = ref(false);
const unknown = ref(false);
const error = ref("");
const note = ref("");
const base = computed(() => costBase(props.company.id));
const items = computed(() => new Map((props.snapshot?.items ?? []).map(item => [item.key, item])));
const legacyActive = computed(() => (props.snapshot?.items ?? []).filter(item => item.legacy_state === "active").length);
const ordered = computed(() => Object.entries(draft.value).sort(([, a], [, b]) => scopeRank(b.scope) - scopeRank(a.scope)));
const BASE_KINDS: Tier["kind"][] = ["markup", "gross_margin", "fixed_addition", "fixed_price"];
let generation = 0;
const changedRows = computed(() => preview.value ? preview.value.result.after.filter((row, index) =>
  row.net_unit_price !== preview.value!.result.before[index]?.net_unit_price || row.rule.id !== preview.value!.result.before[index]?.rule.id).length : 0);

function scopeRank(scope: RuleScope): number { return { line: 5, customer_item: 4, customer: 3, item: 2, company: 1 }[scope]; }
function itemLabel(key: string): string { const item = items.value.get(key); return item ? `${item.name} · ${item.spec || "无规格"}` : "已不存在的品目"; }
function touch(): void { dirty.value = true; preview.value = null; }

function blank(): Form {
  return { id: `r-${Date.now().toString(36)}`, scope: "company", customer: "", item_key: "", kind: "markup", value: "", price_basis: "net",
    valid_from: "", valid_to: "", rate: "", minimum: "", special: false, rounding: false, increment: "1", ending: "0", mode: "ceil", round_basis: "net",
    tier_basis: "quantity", tiers: [{ from: "0", kind: "markup", value: "" }] };
}
function edit(id: string): void {
  const rule = draft.value[id]!;
  form.value = { ...blank(), id, scope: rule.scope, customer: rule.customer, item_key: rule.item_key, kind: rule.kind, value: rule.value ?? "",
    price_basis: rule.price_basis, valid_from: rule.valid_from, valid_to: rule.valid_to, rate: rule.output_tax_rate_percent ?? "",
    minimum: rule.minimum_margin_percent ?? "", special: rule.tax_method === "special", rounding: !!rule.rounding,
    increment: rule.rounding?.increment ?? "1", ending: rule.rounding?.ending ?? "0", mode: rule.rounding?.mode ?? "ceil",
    round_basis: rule.rounding?.basis ?? "net", tier_basis: rule.tier_basis ?? "quantity", tiers: rule.tiers?.map(tier => ({ ...tier })) ?? blank().tiers };
  formError.value = "";
}
function removeRule(id: string): void { const next = { ...draft.value }; delete next[id]; draft.value = next; touch(); }

// Builds exactly the backend's normalized shape; optional fields are omitted, never null.
function build(value: Form): PricingRule | string {
  const needsCustomer = value.scope === "customer" || value.scope === "customer_item";
  const needsItem = value.scope === "item" || value.scope === "customer_item" || value.scope === "line";
  if (needsCustomer && !value.customer.trim()) return "该范围须填写客户。";
  if (needsItem && !value.item_key) return "该范围须选择品目。";
  if (value.valid_from && value.valid_to && value.valid_from > value.valid_to) return "开始日期不能晚于结束日期。";
  const rule: PricingRule = { scope: value.scope, customer: needsCustomer ? value.customer.trim() : "", item_key: needsItem ? value.item_key : "",
    kind: value.kind, valid_from: value.valid_from, valid_to: value.valid_to, price_basis: value.kind === "fixed_price" ? value.price_basis : "net",
    tax_method: value.special ? "special" : "ordinary" };
  if (value.kind === "tiered") {
    if (!value.tiers.length || value.tiers[0]!.from !== "0") return "阶梯须从 0 开始。";
    for (let index = 0; index < value.tiers.length; index += 1) {
      const tier = value.tiers[index]!;
      if (!decimalText(tier.from) || !decimalText(tier.value)) return `第 ${index + 1} 档的起点或数值无效。`;
      if (index && Number(tier.from) <= Number(value.tiers[index - 1]!.from)) return "阶梯起点须严格递增。";
    }
    rule.tier_basis = value.tier_basis;
    rule.tiers = value.tiers.map(tier => ({ from: tier.from.trim(), kind: tier.kind, value: tier.value.trim(), ...(tier.kind === "fixed_price" ? { price_basis: tier.price_basis ?? "net" } : {}) }));
  } else {
    if (!decimalText(value.value)) return "规则值须为非负数字（最多 8 位小数）。";
    if (value.kind === "gross_margin" && Number(value.value) >= 100) return "目标毛利率须小于 100%。";
    rule.value = value.value.trim();
  }
  for (const [field, text] of [["output_tax_rate_percent", value.rate], ["minimum_margin_percent", value.minimum]] as const) {
    if (!text.trim()) continue;
    if (!decimalText(text) || Number(text) >= 100) return "税率与最低毛利须为小于 100 的数字。";
    rule[field] = text.trim();
  }
  if (value.rounding) {
    if (!decimalText(value.increment) || !decimalText(value.ending) || Number(value.ending) >= Number(value.increment)) return "取整步长与尾数须为数字，且尾数小于步长。";
    rule.rounding = { increment: value.increment.trim(), ending: value.ending.trim(), mode: value.mode, basis: value.round_basis };
  }
  return rule;
}
function saveForm(): void {
  if (!form.value) return;
  const rule = build(form.value);
  if (typeof rule === "string") { formError.value = rule; return; }
  draft.value = { ...draft.value, [form.value.id]: rule };
  form.value = null;
  touch();
}

async function runPreview(): Promise<void> {
  const snapshot = props.snapshot;
  if (!snapshot || unknown.value) return;
  const mine = generation;
  // legacy_migrated is deliberately omitted: the backend then keeps the saved migration
  // list, so editing rules here cannot re-enable or drop v1 manual markups by accident.
  const body: Record<string, unknown> = { revision: snapshot.revision, pricing_date: snapshot.pricing_date, customer: previewCustomer.value.trim(),
    rules_revision: snapshot.rules_revision, rules: draft.value };
  if (snapshot.items.length > 500) body.lines = snapshot.items.slice(0, 500).map(item => ({ key: item.key, quantity: "1" }));
  saving.value = true;
  error.value = "";
  try {
    const result = await request<RulesPreview>(`${base.value}/rules/preview`, { method: "POST", body, timeoutMs: 120_000 });
    if (mine === generation) preview.value = { body, result };
  } catch (cause) {
    if (mine !== generation) return;
    error.value = errorText(cause);
    if (cause instanceof ApiError && cause.status === 409) emit("reload");
  } finally { if (mine === generation) saving.value = false; }
}

async function save(): Promise<void> {
  const current = preview.value;
  if (!current || saving.value) return;
  const mine = generation;
  saving.value = true;
  try {
    const result = await request<{ changed: boolean }>(`${base.value}/rules`, { method: "PUT", body: { ...current.body, preview_hash: current.result.preview_hash, confirm: true }, timeoutMs: 120_000 });
    if (mine !== generation) return;
    confirming.value = false;
    preview.value = null;
    dirty.value = false;
    toast(result.changed ? "定价规则已保存；旧成本表与已开快照未改。" : "规则没有变化，未写入。");
    emit("changed");
  } catch (cause) {
    if (mine !== generation) return;
    confirming.value = false;
    preview.value = null;
    if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
      error.value = errorText(cause);
      if (cause.status === 409) emit("reload");
    } else {
      unknown.value = true;
      error.value = "规则保存结果待核对，请重新读取规则；不会自动重发。";
    }
  } finally { if (mine === generation) saving.value = false; }
}

function discard(): void { draft.value = { ...(props.snapshot?.rules ?? {}) }; dirty.value = false; preview.value = null; note.value = ""; }

watch(() => props.snapshot, snapshot => {
  generation += 1;
  saving.value = false;
  confirming.value = false;
  // The parent replaces this snapshot only after a successful GET. An unchanged
  // revision can mean the unknown PUT never wrote; it must also unlock a fresh preview.
  if (snapshot && unknown.value) { unknown.value = false; error.value = ""; }
  preview.value = null;
  if (!dirty.value) { draft.value = { ...(props.snapshot?.rules ?? {}) }; note.value = ""; }
  else note.value = "成本或规则来源已变化：未保存的修改仍保留，请重新试算后再保存。";
}, { immediate: true });
watch(() => props.company.id, () => { generation += 1; saving.value = false; confirming.value = false; dirty.value = false; form.value = null; unknown.value = false; error.value = ""; discard(); });
onBeforeUnmount(() => { generation += 1; });
</script>

<template>
  <section class="cost-rules" aria-label="定价规则">
    <p class="overview-notice">规则按 单行 &gt; 客户×品目 &gt; 客户 &gt; 品目 &gt; 公司默认 取用；同层同对象生效期不得重叠。修改先试算，确认后整份替换保存到本公司成本目录「成本定价规则.json」。</p>
    <p v-if="legacyActive" class="banner banner--note">还有 {{ legacyActive }} 个旧行级加价率按单行规则生效，可在“品目与迁移”中对照后迁移。</p>
    <p v-if="note" class="banner banner--note" role="status">{{ note }}</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }} <button v-if="unknown" type="button" @click="emit('reload')">重新读取</button></p>
    <div class="toolbar">
      <button type="button" :disabled="busy || saving || unknown || !snapshot" @click="form = blank(); formError = ''">新增规则</button>
      <button v-if="dirty" type="button" class="ghost" :disabled="saving" @click="discard">放弃修改</button>
      <span v-if="dirty" class="muted">有未保存的修改</span>
    </div>
    <div class="overview-table-wrap"><table class="grid" aria-label="定价规则列表">
      <thead><tr><th>标识</th><th>范围</th><th>对象</th><th>规则</th><th>生效期</th><th>税率%</th><th>最低毛利%</th><th>取整</th><th></th></tr></thead>
      <tbody>
        <tr v-for="[id, rule] in ordered" :key="id">
          <td>{{ id }}</td><td>{{ RULE_SCOPE_LABELS[rule.scope] }}</td>
          <td>{{ [rule.customer, rule.item_key ? itemLabel(rule.item_key) : ""].filter(Boolean).join(" × ") || "全部" }}</td>
          <td>{{ ruleSummary(rule) }}<template v-if="rule.tax_method === 'special'"> · 特殊计税</template></td>
          <td>{{ rule.valid_from || "不限" }} 至 {{ rule.valid_to || "不限" }}</td>
          <td>{{ rule.output_tax_rate_percent ?? "—" }}</td><td>{{ rule.minimum_margin_percent ?? "—" }}</td>
          <td>{{ rule.rounding ? `${rule.rounding.basis === "gross" ? "含税" : "除税"}步长 ${rule.rounding.increment} 尾数 ${rule.rounding.ending}` : "—" }}</td>
          <td><button type="button" :disabled="saving || unknown" @click="edit(id)">编辑</button> <button type="button" class="ghost" :disabled="saving || unknown" @click="removeRule(id)">删除</button></td>
        </tr>
        <tr v-if="!ordered.length"><td colspan="9" class="muted">没有已保存规则；未命中时按默认加价率 {{ snapshot?.default_markup_percent ?? "8" }}% 给参考价。</td></tr>
      </tbody>
    </table></div>
    <div class="toolbar">
      <label class="field">试算客户<input v-model="previewCustomer" list="cost-rule-customers" aria-label="试算客户" placeholder="不选则按无客户试算" @input="preview = null"></label>
      <button type="button" class="primary" :disabled="busy || saving || unknown || !snapshot" :aria-busy="saving" @click="runPreview">试算</button>
      <button type="button" :disabled="!preview || saving || unknown" @click="confirming = true">确认保存…</button>
    </div>
    <template v-if="preview">
      <p>受影响 {{ changedRows }} 行（数量按 1 试算<template v-if="(snapshot?.items.length ?? 0) > 500">，仅前 500 个品目</template>）。</p>
      <div class="overview-table-wrap"><table class="grid" aria-label="规则试算对照">
        <thead><tr><th>品名 · 规格</th><th>原规则</th><th>新规则</th><th class="num">原除税单价</th><th class="num">新除税单价</th><th class="num">新含税单价</th><th>状态</th></tr></thead>
        <tbody><tr v-for="(after, index) in preview.result.after" :key="after.key" :class="{ 'cost-rules__changed': after.net_unit_price !== preview.result.before[index]?.net_unit_price || after.rule.id !== preview.result.before[index]?.rule.id }">
          <td>{{ after.name }} · {{ after.spec || "无规格" }}</td>
          <td>{{ RULE_SOURCE_LABELS[preview.result.before[index]!.rule.source] }} · {{ ruleSummary(preview.result.before[index]!.rule) }}</td>
          <td>{{ RULE_SOURCE_LABELS[after.rule.source] }} · {{ ruleSummary(after.rule) }}</td>
          <td class="num">{{ money(preview.result.before[index]!.net_unit_price) }}</td><td class="num">{{ money(after.net_unit_price) }}</td><td class="num">{{ money(after.gross_unit_price) }}</td>
          <td><details><summary>{{ after.state === "priced" ? "已出价" : "待核对" }}</summary><ol><li v-for="step in after.steps" :key="step">{{ step }}</li></ol><p v-if="after.warnings.length">{{ after.warnings.join("；") }}</p></details></td>
        </tr></tbody>
      </table></div>
    </template>
    <datalist id="cost-rule-customers"><option v-for="name in snapshot?.customers ?? []" :key="name" :value="name" /></datalist>
    <WsModal v-if="form" title="定价规则" :wide="true" @close="form = null">
      <p v-if="formError" class="banner banner--error" role="alert">{{ formError }}</p>
      <div class="cost-rules__form">
        <label class="field">范围<select v-model="form.scope" aria-label="规则范围"><option v-for="(label, scope) in RULE_SCOPE_LABELS" :key="scope" :value="scope">{{ label }}</option></select></label>
        <label v-if="form.scope === 'customer' || form.scope === 'customer_item'" class="field">客户<input v-model="form.customer" list="cost-rule-customers" aria-label="规则客户" maxlength="200"></label>
        <label v-if="['item', 'customer_item', 'line'].includes(form.scope)" class="field">品目<select v-model="form.item_key" aria-label="规则品目"><option value="">请选择</option><option v-for="item in snapshot?.items ?? []" :key="item.key" :value="item.key">{{ item.name }} · {{ item.spec || "无规格" }} · {{ item.unit }}</option></select></label>
        <label class="field">类型<select v-model="form.kind" aria-label="规则类型"><option v-for="(label, kind) in RULE_KIND_LABELS" :key="kind" :value="kind">{{ label }}</option></select></label>
        <label v-if="form.kind !== 'tiered'" class="field">{{ form.kind === "market" ? "最低加价率%" : form.kind === "fixed_price" ? "价格" : form.kind === "fixed_addition" ? "加价额" : "百分比" }}<input v-model="form.value" aria-label="规则值" inputmode="decimal"></label>
        <label v-if="form.kind === 'fixed_price'" class="field">价格口径<select v-model="form.price_basis" aria-label="价格口径"><option value="net">除税</option><option value="gross">含税</option></select></label>
        <label class="field">生效起<input v-model="form.valid_from" type="date" aria-label="生效起"></label>
        <label class="field">生效止<input v-model="form.valid_to" type="date" aria-label="生效止"></label>
        <label class="field">税率覆盖%<input v-model="form.rate" aria-label="税率覆盖" inputmode="decimal" placeholder="空 = 品目/公司税率"></label>
        <label class="field">最低毛利%<input v-model="form.minimum" aria-label="最低毛利" inputmode="decimal" placeholder="低于时只提示"></label>
        <label><input v-model="form.special" type="checkbox"> 特殊计税（不计算，需人工确认）</label>
        <label><input v-model="form.rounding" type="checkbox"> 取整</label>
      </div>
      <div v-if="form.rounding" class="cost-rules__form">
        <label class="field">步长<input v-model="form.increment" aria-label="取整步长" inputmode="decimal"></label>
        <label class="field">尾数<input v-model="form.ending" aria-label="取整尾数" inputmode="decimal"></label>
        <label class="field">方向<select v-model="form.mode" aria-label="取整方向"><option value="ceil">向上</option><option value="floor">向下</option><option value="half_up">四舍五入</option></select></label>
        <label class="field">口径<select v-model="form.round_basis" aria-label="取整口径"><option value="net">除税</option><option value="gross">含税</option></select></label>
      </div>
      <fieldset v-if="form.kind === 'tiered'" class="cost-rules__tiers">
        <legend>阶梯（整行按命中档价格，非累进）</legend>
        <label class="field">分档依据<select v-model="form.tier_basis" aria-label="分档依据"><option value="quantity">本次数量</option><option value="amount">本次除税基准金额</option></select></label>
        <div v-for="(tier, index) in form.tiers" :key="index" class="cost-rules__form">
          <label class="field">起点<input v-model="tier.from" :aria-label="`第 ${index + 1} 档起点`" :disabled="index === 0" inputmode="decimal"></label>
          <label class="field">类型<select v-model="tier.kind" :aria-label="`第 ${index + 1} 档类型`"><option v-for="kind in BASE_KINDS" :key="kind" :value="kind">{{ RULE_KIND_LABELS[kind] }}</option></select></label>
          <label class="field">数值<input v-model="tier.value" :aria-label="`第 ${index + 1} 档数值`" inputmode="decimal"></label>
          <select v-if="tier.kind === 'fixed_price'" v-model="tier.price_basis" :aria-label="`第 ${index + 1} 档价格口径`"><option value="net">除税</option><option value="gross">含税</option></select>
          <button v-if="index" type="button" class="ghost" @click="form.tiers.splice(index, 1)">删除档</button>
        </div>
        <button type="button" :disabled="form.tiers.length >= 50" @click="form.tiers.push({ from: '', kind: 'markup', value: '' })">添加一档</button>
      </fieldset>
      <p v-if="form.kind === 'market'" class="muted">市场价由报价时逐行填写（含来源与有效期），规则只保存最低加价率底线；不联网取价。</p>
      <div class="actions"><button type="button" class="primary" @click="saveForm">放入草稿</button><button type="button" @click="form = null">取消</button></div>
    </WsModal>
    <WsModal v-if="confirming && preview" title="确认保存定价规则" @close="!saving && (confirming = false)">
      <p>将以试算时的 {{ Object.keys(preview.result.rules).length }} 条规则整份替换本公司规则文件（规则版本 {{ preview.result.rules_revision }} → 新版本）。受影响 {{ changedRows }} 行。</p>
      <p class="muted">不改旧成本发票汇总.xlsx、已开快照或 v1 价格；来源变化会被拒绝，需重新试算。</p>
      <div class="actions"><button type="button" class="primary" :disabled="saving" :aria-busy="saving" @click="save">{{ saving ? "保存中…" : "确认保存规则" }}</button><button type="button" :disabled="saving" @click="confirming = false">取消</button></div>
    </WsModal>
  </section>
</template>

<style scoped>
.cost-rules__form { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: end; margin-bottom: 8px; }
.cost-rules__tiers { border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; margin-bottom: 8px; }
.cost-rules__changed td { background: var(--ws-selected); }
</style>
