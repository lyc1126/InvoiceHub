// Company cost V2 contract (/api/v1/companies/{id}/cost-analysis/v2). Every amount is an exact
// decimal string and unknown stays null; views must show "—"/待核对 rather than coerce to 0.
// Writes are always preview → explicit confirm with the preview_hash the user saw; a 409
// means the sources moved and the view rereads instead of replaying the write.
import { ApiError } from "./client";
import { money } from "../format";

export type RuleScope = "company" | "item" | "customer" | "customer_item" | "line";
export type RuleKind = "markup" | "gross_margin" | "fixed_addition" | "fixed_price" | "tiered" | "market";
export type PriceBasis = "net" | "gross";
export interface Rounding { increment: string; ending: string; mode: "ceil" | "floor" | "half_up"; basis: PriceBasis }
export interface Tier { from: string; kind: Exclude<RuleKind, "tiered" | "market">; value: string; price_basis?: PriceBasis }
export interface PricingRule {
  scope: RuleScope; customer: string; item_key: string; kind: RuleKind; value?: string;
  valid_from: string; valid_to: string; price_basis: PriceBasis; tax_method: "ordinary" | "special";
  output_tax_rate_percent?: string; minimum_margin_percent?: string; rounding?: Rounding;
  tier_basis?: "quantity" | "amount"; tiers?: Tier[];
}
export interface AppliedRule extends PricingRule { id: string; source: "saved" | "legacy" | "manual" | "fallback" }
export interface IssuedFigures { source: string; quantity: string | null; net_amount: string | null; tax_amount: string | null; gross_amount: string | null; invoice_count?: number }
export interface V1Reference { cost_unit_price: string | null; net_unit_price: string | null; gross_unit_price: string | null; markup_percent: string; cost_basis: string; basis: string }
export interface CostItem {
  key: string; name: string; spec: string; unit: string; quantity: string; category_key: string; account_code: string;
  closing_quantity: string | null; closing_amount: string | null; closing_weighted_unit_cost: string | null;
  historical_average_unit_cost: string | null; latest_purchase_unit_cost: string | null; latest_purchase_date: string | null;
  cost_tax_basis: string; output_tax_rate_percent: string; legacy_markup_percent: string | null;
  legacy_state: "active" | "migrated" | null; v1_reference: V1Reference;
  manual_issued_snapshot: IssuedFigures; actual_issued: IssuedFigures | null; issued: IssuedFigures; warnings: string[];
}
export interface BookReconciliationRow {
  key?: string; account_code: string; name: string; unit: string; state: "matched" | "different" | "needs_review" | "unassigned";
  expected_quantity?: string; expected_amount?: string; book_quantity: string | null; book_amount: string | null;
  quantity_difference: string | null; amount_difference: string | null;
}
export interface CostSnapshot {
  company_id: string; pricing_date: string; revision: string; rules_revision: number; rules: Record<string, PricingRule>;
  legacy_migrated: string[]; customers: string[]; default_markup_percent: string; items: CostItem[]; complete: boolean;
  warnings: CostWarning[]; basis_label: string;
  sources: Record<string, { freshness?: { state: string; message?: string } }>;
  book_reconciliation: { state: string; message: string; missing_months: string[]; items: BookReconciliationRow[] };
}
export interface MarketReference { unit_price: string; price_basis: PriceBasis; observed_on: string; valid_to: string; source: string }
export interface QuoteLine { key: string; quantity: string; output_tax_rate_percent?: string; tier_amount?: string; market_reference?: MarketReference }
export interface QuoteRow {
  key: string; name: string; spec: string; unit: string; cost_unit_price: string | null; rule: AppliedRule; overridden_rules: AppliedRule[];
  quantity: string; output_tax_rate_percent: string; net_unit_price: string | null; gross_unit_price: string | null;
  net_amount: string | null; tax_amount: string | null; gross_amount: string | null; markup_percent: string | null;
  gross_margin_percent: string | null; state: "priced" | "needs_review"; warnings: string[]; steps: string[];
  tier?: { basis: string; metric: string; from: string; to: string | null; kind: string; value: string };
  market_reference?: MarketReference | null; minimum_net_unit_price?: string;
}
export interface QuoteRequest { revision: string; pricing_date: string; customer: string; lines: QuoteLine[] }
export interface RulesPreviewRequest extends QuoteRequest { rules_revision: number; rules: Record<string, PricingRule>; legacy_migrated?: string[] }
export interface RulesPreview { revision: string; rules_revision: number; preview_hash: string; before: QuoteRow[]; after: QuoteRow[]; rules: Record<string, PricingRule>; legacy_migrated: string[] }
export interface MigrationRow {
  key: string; name: string; spec: string; unit: string; output_tax_rate_percent: string;
  legacy_markup_percent: string | null; legacy_state: "active" | "migrated" | null; v1: V1Reference;
  v2: { cost_unit_price: string | null; historical_average_unit_cost: string | null; latest_purchase_unit_cost: string | null;
    rule: { id: string; source: AppliedRule["source"]; scope: RuleScope; kind: RuleKind; value?: string; price_basis: PriceBasis };
    net_unit_price: string | null; gross_unit_price: string | null; state: string; warnings: string[]; steps: string[] };
  v2_without_legacy: { rule: { id: string; source: string; kind: RuleKind; value?: string }; net_unit_price: string | null; gross_unit_price: string | null; state: string } | null;
  difference_net_unit_price: string | null; state: "same" | "different" | "needs_review"; warnings: string[];
}
export interface MigrationView {
  pricing_date: string; revision: string; rules_revision: number; legacy_migrated: string[]; complete: boolean; rows: MigrationRow[];
  summary: Record<"same" | "different" | "needs_review" | "legacy_active" | "legacy_migrated" | "legacy_none", number>; basis_label: string;
}

export const RULE_KIND_LABELS: Record<RuleKind, string> = {
  markup: "加价率", gross_margin: "目标毛利率", fixed_addition: "固定加价额", fixed_price: "固定价", tiered: "阶梯", market: "市场参照",
};
export const RULE_SCOPE_LABELS: Record<RuleScope, string> = {
  line: "单行", customer_item: "客户 × 品目", customer: "客户", item: "品目", company: "公司默认",
};
export const RULE_SOURCE_LABELS: Record<AppliedRule["source"], string> = {
  saved: "已保存规则", legacy: "旧行级加价率", manual: "单行临时", fallback: "默认加价率",
};

export function costBase(companyId: string): string {
  return `/api/v1/companies/${encodeURIComponent(companyId)}/cost-analysis/v2`;
}

export function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

// Same 0–8 decimal, ≤15 integer digit shape the backend enforces; the view rejects before posting.
export function decimalText(value: string): boolean {
  return /^(?:0|[1-9]\d{0,14})(?:\.\d{1,8})?$/.test(value.trim());
}

// Weighted unit costs arrive at 50-digit precision. Display them half-up to 4 decimals on the
// string (no float); callers keep the exact value in a title and never post the shortened text.
export function unitCost(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "未知";
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return value;
  const [, sign = "", whole = "", fraction = ""] = match;
  if (fraction.length <= 4) return money(value);
  const scaled = BigInt(whole + fraction.slice(0, 4)) + (Number(fraction[4]) >= 5 ? 1n : 0n);
  const text = scaled.toString().padStart(5, "0");
  return money(`${sign}${text.slice(0, -4)}.${text.slice(-4)}`.replace(/\.?0+$/, "") || "0");
}

export type CostWarning = string | { code?: string; message: string };
export function warningText(warning: CostWarning): string {
  return typeof warning === "string" ? warning : warning.message;
}

export function ruleSummary(rule: Pick<PricingRule, "kind" | "value" | "price_basis" | "tier_basis" | "tiers">): string {
  if (rule.kind === "tiered") return `阶梯（按${rule.tier_basis === "amount" ? "金额" : "数量"}，${rule.tiers?.length ?? 0} 档）`;
  if (rule.kind === "fixed_price") return `固定${rule.price_basis === "gross" ? "含税" : "除税"}价 ${rule.value}`;
  if (rule.kind === "fixed_addition") return `成本 + ${rule.value}`;
  if (rule.kind === "market") return `市场价，底线加价 ${rule.value}%`;
  return `${RULE_KIND_LABELS[rule.kind]} ${rule.value}%`;
}

// V2 exports are in-memory attachments (never written beside v1 workbooks). The response is
// read as a blob and saved through a temporary link; JSON errors surface as ApiError.
export async function downloadPost(path: string, body: unknown, filename: string): Promise<void> {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), credentials: "same-origin" })
    .catch(() => { throw new ApiError("无法连接本机服务", 0); });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string; error?: { code?: string } } | null;
    throw new ApiError(payload?.detail ?? `导出失败（HTTP ${response.status}）`, response.status, payload?.error?.code ?? "");
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
