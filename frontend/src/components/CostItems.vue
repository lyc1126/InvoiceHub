<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import {
  costBase, downloadPost, RULE_KIND_LABELS, RULE_SOURCE_LABELS, unitCost,
  type CostItem, type CostSnapshot, type MigrationRow, type MigrationView, type PricingRule, type RulesPreview,
} from "../api/costV2";
import type { Company } from "../api/types";
import { errorText, money } from "../format";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

const props = defineProps<{ company: Company; snapshot: CostSnapshot | null; busy: boolean }>();
const emit = defineEmits<{ changed: []; reload: [] }>();
const view = ref<"items" | "migration">("items");
const filter = ref("");
const page = ref(0);
const migration = ref<MigrationView | null>(null);
const migrationFilter = ref<"all" | "different" | "legacy">("all");
const loading = ref(false);
const error = ref("");
const choices = ref<Record<string, "convert" | "drop">>({});
const pending = ref<{ body: Record<string, unknown>; preview: RulesPreview } | null>(null);
const saving = ref(false);
const unknown = ref(false);
const base = computed(() => costBase(props.company.id));
const STATE_LABELS = { same: "一致", different: "不同", needs_review: "待核对" } as const;
const LEGACY_LABELS = { active: "仍生效", migrated: "已迁移/不沿用" } as const;
let generation = 0;

const shownItems = computed(() => {
  const words = filter.value.trim().toLowerCase();
  return (props.snapshot?.items ?? []).filter(item => !words || `${item.name} ${item.spec}`.toLowerCase().includes(words));
});
const pageItems = computed(() => shownItems.value.slice(page.value * 50, (page.value + 1) * 50));
const rows = computed(() => (migration.value?.rows ?? []).filter(row => migrationFilter.value === "all"
  || (migrationFilter.value === "different" ? row.state !== "same" : row.legacy_state === "active")));
const active = computed(() => (migration.value?.rows ?? []).filter(row => row.legacy_state === "active"));
const batch = computed(() => active.value.slice(0, 500));

// Actual sales and the v1 hand-entered snapshot are alternative evidence for the same
// quantity; showing one sum would double count, so the actual figures win when present.
function issued(item: CostItem): string {
  if (item.actual_issued) return `${item.actual_issued.quantity ?? "未知"}（销项实际）`;
  return item.manual_issued_snapshot.quantity ? `${item.manual_issued_snapshot.quantity}（手填快照）` : "—";
}
function difference(row: MigrationRow): string {
  if (row.difference_net_unit_price === null) return "待核对";
  return row.difference_net_unit_price.startsWith("-") ? money(row.difference_net_unit_price) : `+${money(row.difference_net_unit_price)}`;
}

async function loadMigration(): Promise<void> {
  if (!props.snapshot) return;
  const mine = ++generation;
  loading.value = true;
  try {
    const result = await request<MigrationView>(`${base.value}/migration?pricing_date=${props.snapshot.pricing_date}`, { timeoutMs: 120_000 });
    if (mine !== generation) return;
    migration.value = result;
    choices.value = Object.fromEntries(result.rows.filter(row => row.legacy_state === "active").map(row => [row.key, choices.value[row.key] ?? "convert"]));
    error.value = "";
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) loading.value = false; }
}

function ruleId(rules: Record<string, PricingRule>, key: string): string {
  const stem = `legacy-${key.slice(0, 12)}`;
  let id = stem;
  for (let suffix = 2; id in rules; suffix += 1) id = `${stem}-${suffix}`;
  return id;
}

async function previewMigration(): Promise<void> {
  const snapshot = props.snapshot;
  if (!snapshot || !migration.value || !batch.value.length || unknown.value) return;
  const mine = generation;
  const rules: Record<string, PricingRule> = { ...snapshot.rules };
  for (const row of batch.value) {
    if (choices.value[row.key] !== "convert") continue;
    // An open-ended saved line rule already outranks the v1 rate; adding another would
    // overlap and be rejected, so such rows are only marked migrated.
    const covered = Object.values(rules).some(rule => rule.scope === "line" && rule.item_key === row.key && !rule.valid_from && !rule.valid_to);
    if (!covered) rules[ruleId(rules, row.key)] = { scope: "line", customer: "", item_key: row.key, kind: "markup", value: row.legacy_markup_percent ?? "0", valid_from: "", valid_to: "", price_basis: "net", tax_method: "ordinary" };
  }
  // The saved list is unioned, never replaced: rows migrated earlier must not silently
  // fall back to their v1 manual rate when a later batch is confirmed.
  const legacy = [...new Set([...snapshot.legacy_migrated, ...batch.value.map(row => row.key)])].sort();
  const body = { revision: snapshot.revision, pricing_date: snapshot.pricing_date, customer: "", rules_revision: snapshot.rules_revision,
    rules, legacy_migrated: legacy, lines: batch.value.map(row => ({ key: row.key, quantity: "1" })) };
  saving.value = true;
  error.value = "";
  try {
    const preview = await request<RulesPreview>(`${base.value}/rules/preview`, { method: "POST", body, timeoutMs: 120_000 });
    if (mine === generation) pending.value = { body, preview };
  } catch (cause) {
    if (mine !== generation) return;
    error.value = errorText(cause);
    if (cause instanceof ApiError && cause.status === 409) emit("reload");
  } finally { if (mine === generation) saving.value = false; }
}

async function confirmMigration(): Promise<void> {
  const current = pending.value;
  if (!current || saving.value) return;
  const mine = generation;
  saving.value = true;
  try {
    await request(`${base.value}/rules`, { method: "PUT", body: { ...current.body, preview_hash: current.preview.preview_hash, confirm: true }, timeoutMs: 120_000 });
    if (mine !== generation) return;
    pending.value = null;
    toast(`已迁移 ${current.preview.after.length} 个旧行级加价率；旧成本表与已开快照未改。`);
    emit("changed");
  } catch (cause) {
    if (mine !== generation) return;
    pending.value = null;
    if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
      error.value = errorText(cause);
      if (cause.status === 409) emit("reload");
    } else {
      unknown.value = true;
      error.value = "迁移保存结果待核对，请重新读取；不会自动重发。";
    }
  } finally { if (mine === generation) saving.value = false; }
}

async function exportComparison(): Promise<void> {
  if (!migration.value) return;
  try {
    await downloadPost(`${base.value}/migration/export`, { revision: migration.value.revision, pricing_date: migration.value.pricing_date },
      `成本V2开票参考对照-${migration.value.pricing_date}.xlsx`);
  } catch (cause) {
    error.value = errorText(cause);
    if (cause instanceof ApiError && cause.status === 409) void loadMigration();
  }
}

watch(filter, () => { page.value = 0; });
watch(() => props.snapshot, snapshot => {
  generation += 1;
  saving.value = false;
  pending.value = null;
  migration.value = null;
  // A successful read-back may return the same rules revision when the PUT never
  // reached disk. Missing/failed reads must keep the unknown-write lock in place.
  if (snapshot && unknown.value) { unknown.value = false; error.value = ""; }
  if (view.value === "migration" && snapshot) void loadMigration();
});
watch(view, () => { if (view.value === "migration" && props.snapshot) void loadMigration(); });
watch(() => props.company.id, () => { generation += 1; saving.value = false; loading.value = false; migration.value = null; pending.value = null; unknown.value = false; error.value = ""; choices.value = {}; });
onBeforeUnmount(() => { generation += 1; });
</script>

<template>
  <section class="cost-items" aria-label="品目与迁移">
    <div class="tabs" role="tablist" aria-label="品目视图">
      <button type="button" role="tab" :aria-selected="view === 'items'" @click="view = 'items'">品目总览</button>
      <button type="button" role="tab" :aria-selected="view === 'migration'" @click="view = 'migration'">新旧对照与迁移</button>
    </div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }} <button v-if="unknown" type="button" @click="emit('reload')">重新读取</button></p>
    <template v-if="view === 'items'">
      <p class="overview-notice">成本按品类+单位月末一次加权，同品类各规格共用结存单价；结存成本未知时不回退历史均价。“已开”有销项实际时取实际，否则显示旧手填快照，两者不相加。</p>
      <div class="toolbar"><label class="field">筛选<input v-model="filter" aria-label="筛选品目" placeholder="品名或规格"></label><span class="muted">{{ shownItems.length }} 个品目</span></div>
      <div class="overview-table-wrap"><table class="grid" aria-label="品目总览">
        <thead><tr><th>品名</th><th>规格</th><th>单位</th><th class="num">购入数量</th><th class="num">品类结存数量</th><th class="num">结存加权成本</th><th class="num">历史均价</th><th class="num">最近进价</th><th>成本口径</th><th class="num">税率%</th><th>库存科目</th><th>已开</th><th>旧加价率</th><th>提示</th></tr></thead>
        <tbody><tr v-for="item in pageItems" :key="item.key">
          <td>{{ item.name }}</td><td>{{ item.spec || "—" }}</td><td>{{ item.unit }}</td>
          <td class="num">{{ item.quantity }}</td><td class="num">{{ item.closing_quantity ?? "—" }}</td>
          <td class="num" :title="item.closing_weighted_unit_cost ?? ''">{{ unitCost(item.closing_weighted_unit_cost) }}</td>
          <td class="num" :title="item.historical_average_unit_cost ?? ''">{{ item.historical_average_unit_cost === null ? "—" : unitCost(item.historical_average_unit_cost) }}</td>
          <td class="num">{{ item.latest_purchase_unit_cost === null ? "—" : unitCost(item.latest_purchase_unit_cost) }}<template v-if="item.latest_purchase_date"><br><small>{{ item.latest_purchase_date }}</small></template></td>
          <td>{{ item.cost_tax_basis }}</td><td class="num">{{ item.output_tax_rate_percent }}</td>
          <td>{{ item.account_code || "未对照" }}</td><td>{{ issued(item) }}</td>
          <td>{{ item.legacy_markup_percent === null ? "—" : `${item.legacy_markup_percent}%（${item.legacy_state ? LEGACY_LABELS[item.legacy_state] : ""}）` }}</td>
          <td><small>{{ item.warnings.join("；") }}</small></td>
        </tr></tbody>
      </table></div>
      <div class="toolbar"><button type="button" :disabled="page === 0" @click="page--">上一页</button><span>{{ page + 1 }} / {{ Math.max(1, Math.ceil(shownItems.length / 50)) }}</span><button type="button" :disabled="(page + 1) * 50 >= shownItems.length" @click="page++">下一页</button></div>
    </template>
    <template v-else>
      <p class="overview-notice">v1 按全部历史进项均价 × (1 + 行加价率) 给价，V2 按品类结存加权成本与规则给价，两者本就可能不同；对照只读，不改旧成本发票汇总.xlsx、已开快照或规则。</p>
      <p v-if="loading && !migration" class="muted">正在读取对照…</p>
      <template v-if="migration">
        <p>一致 {{ migration.summary.same }} · 不同 {{ migration.summary.different }} · 待核对 {{ migration.summary.needs_review }} · 旧加价率仍生效 {{ migration.summary.legacy_active }} · 已迁移 {{ migration.summary.legacy_migrated }}<template v-if="!migration.complete"> · <b>来源不完整</b></template></p>
        <div class="toolbar">
          <label class="field">显示<select v-model="migrationFilter" aria-label="对照筛选"><option value="all">全部</option><option value="different">仅不同或待核对</option><option value="legacy">仅旧加价率仍生效</option></select></label>
          <button type="button" :disabled="loading" @click="exportComparison">导出 V2 开票参考对照（xlsx）</button>
          <span class="muted">内存导出，不改旧成本发票汇总.xlsx。</span>
        </div>
        <div class="overview-table-wrap"><table class="grid" aria-label="新旧对照">
          <thead><tr><th>品名 · 规格</th><th class="num">v1 成本</th><th class="num">v1 加价率%</th><th class="num">v1 除税单价</th><th class="num">V2 结存成本</th><th>V2 命中规则</th><th class="num">V2 除税单价</th><th class="num">差额</th><th>对照</th><th>旧加价率</th><th>迁移方式</th></tr></thead>
          <tbody><tr v-for="row in rows" :key="row.key" :class="{ 'check--failed': row.state === 'needs_review' }">
            <td>{{ row.name }} · {{ row.spec || "无规格" }} · {{ row.unit }}</td>
            <td class="num">{{ row.v1.cost_unit_price === null ? "未知" : money(row.v1.cost_unit_price) }}<br><small>{{ row.v1.cost_basis }}</small></td>
            <td class="num">{{ row.v1.markup_percent }}</td><td class="num">{{ money(row.v1.net_unit_price) }}</td>
            <td class="num" :title="row.v2.cost_unit_price ?? ''">{{ unitCost(row.v2.cost_unit_price) }}</td>
            <td>{{ RULE_SOURCE_LABELS[row.v2.rule.source] }} · {{ RULE_KIND_LABELS[row.v2.rule.kind] }} {{ row.v2.rule.value ?? "" }}</td>
            <td class="num">{{ money(row.v2.net_unit_price) }}</td>
            <td class="num" :class="{ 'cost-items__up': row.state === 'different' && !row.difference_net_unit_price?.startsWith('-'), 'cost-items__down': row.difference_net_unit_price?.startsWith('-') }">{{ difference(row) }}</td>
            <td>{{ STATE_LABELS[row.state] }}</td>
            <td>{{ row.legacy_markup_percent === null ? "—" : `${row.legacy_markup_percent}%（${row.legacy_state ? LEGACY_LABELS[row.legacy_state] : ""}）` }}</td>
            <td>
              <select v-if="row.legacy_state === 'active'" v-model="choices[row.key]" :aria-label="`迁移方式 ${row.name}`" :disabled="saving || unknown">
                <option value="convert">转为单行规则（保留 {{ row.legacy_markup_percent }}%）</option>
                <option value="drop">不沿用（V2 价 {{ money(row.v2_without_legacy?.net_unit_price ?? null) }}）</option>
              </select>
              <span v-else class="muted">—</span>
            </td>
          </tr></tbody>
        </table></div>
        <div class="actions">
          <button v-if="active.length" type="button" class="primary" :disabled="busy || saving || unknown" :aria-busy="saving" @click="previewMigration">预览迁移（{{ batch.length }} 行）</button>
          <span v-else class="muted">没有待迁移的旧行级加价率。</span>
          <span v-if="active.length > 500" class="muted">超过 500 行，本次只迁移前 500 行，其余确认后再迁移。</span>
        </div>
      </template>
    </template>
    <WsModal v-if="pending" title="确认迁移旧行级加价率" :wide="true" @close="!saving && (pending = null)">
      <p>确认后写入本公司成本目录的「成本定价规则.json」；不改旧成本表、已开快照或工作簿；旧加价率原值保留可查。</p>
      <div class="overview-table-wrap"><table class="grid" aria-label="迁移预览">
        <thead><tr><th>品名 · 规格</th><th>迁移前规则</th><th class="num">迁移前除税单价</th><th>迁移后规则</th><th class="num">迁移后除税单价</th></tr></thead>
        <tbody><tr v-for="(after, index) in pending.preview.after" :key="after.key">
          <td>{{ after.name }} · {{ after.spec || "无规格" }}</td>
          <td>{{ RULE_SOURCE_LABELS[pending.preview.before[index]!.rule.source] }}</td><td class="num">{{ money(pending.preview.before[index]!.net_unit_price) }}</td>
          <td>{{ RULE_SOURCE_LABELS[after.rule.source] }} · {{ RULE_KIND_LABELS[after.rule.kind] }} {{ after.rule.value ?? "" }}</td><td class="num">{{ money(after.net_unit_price) }}</td>
        </tr></tbody>
      </table></div>
      <div class="actions"><button type="button" class="primary" :disabled="saving" :aria-busy="saving" @click="confirmMigration">{{ saving ? "保存中…" : "确认迁移" }}</button><button type="button" :disabled="saving" @click="pending = null">取消</button></div>
    </WsModal>
  </section>
</template>

<style scoped>
.cost-items__up { color: var(--amber); }
.cost-items__down { color: var(--red); }
</style>
