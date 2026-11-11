// Subsets of /api/v1 payloads consumed by the workspace shell. Field names follow
// AppState.health() and AppState.settings(); extend here before using a new field.
export interface HealthPayload {
  ok: boolean;
  product_version: string;
  platform: string;
  background_status: string;
  watch_dir: string;
  target_id: string;
}

export interface SettingsPayload {
  ok: boolean;
  watch_dir: string;
  active_target_id: string;
}

// ---- Company registry and per-company read-only views (WS-07, /api/v1/companies*) ----------

export type TaxpayerType = "general" | "small_scale";
export type SubdirStatus = "present" | "missing" | "not_directory" | "outside_root" | "unreadable" | "root_unavailable";

export interface TaxpayerPeriod {
  effective_from: string;
  taxpayer_type: TaxpayerType;
}

export interface CompanySubdir {
  key: string;
  label: string;
  relative_path: string;
  path: string;
  status: SubdirStatus;
}

export interface Company {
  id: string;
  name: string;
  root_dir: string;
  root_path: string;
  root_status: "present" | "missing" | "not_directory";
  subdirs: CompanySubdir[];
  missing_subdir_count: number;
  taxpayer_periods: TaxpayerPeriod[];
  current_taxpayer_type: TaxpayerType | null;
  current_taxpayer_label: string;
  monitored: boolean;
  monitored_subdir_key: string | null;
}

export interface CompanyListPayload {
  ok: boolean;
  revision: number;
  companies: Company[];
  monitored_company_id: string | null;
  target_id: string;
  watch_dir: string;
}

export interface CostWorkbookRefresh {
  refreshed: boolean;
  reason: "" | "sync_running" | "no_cost_detail";
}

export interface CompanyPayload {
  ok: boolean;
  revision: number;
  company: Company;
  subdir_sources?: Record<string, "standard" | "detected" | "default" | "user">;
  cost_workbook?: CostWorkbookRefresh;
}

export interface CompanyDeletePayload {
  ok: boolean;
  deleted: string;
  revision: number;
  files_touched: number;
  cost_workbook?: CostWorkbookRefresh;
}

export interface SubdirPlanItem {
  key: string;
  label: string;
  relative_path: string;
  path: string;
  action: "create" | "exists" | "blocked";
  reason: string;
}

export interface SubdirPlan {
  ok: boolean;
  company_id: string;
  revision: number;
  items: SubdirPlanItem[];
  create_count: number;
  blocked_count: number;
  plan_hash: string;
}

export interface SubdirCreateResult extends CompanyPayload {
  created: string[];
  skipped: string[];
  failed: { key: string; message: string }[];
}

export type FreshnessState = "monitored" | "fresh" | "stale" | "never_built" | "unknown" | "missing_dir" | "not_checked";

export interface Freshness {
  state: FreshnessState;
  message: string;
  added?: number;
  updated?: number;
  deleted?: number;
  source_file_count?: number;
  complete?: boolean;
}

export interface CompanyDirectory extends CompanySubdir {
  target_id: string;
  active: boolean;
  read_only: boolean;
  projection: {
    summary_exists: boolean;
    summary_updated_at: string;
    cost_detail_exists: boolean;
    cost_detail_updated_at: string;
  };
  freshness: Freshness;
}

export interface DirectoriesPayload {
  ok: boolean;
  revision: number;
  company: Company;
  directories: CompanyDirectory[];
}

export interface InvoiceRow {
  invoice_key: string;
  source_file: string;
  file_format: string;
  invoice_type: string;
  invoice_number: string;
  invoice_date: string;
  seller: string;
  buyer: string;
  amount: string;
  tax_rate: string;
  status: string;
}

export interface DirectoryInvoicesPayload {
  ok: boolean;
  count: number;
  items: InvoiceRow[];
  page?: number;
  page_size?: number;
  read_only: boolean;
  directory: CompanyDirectory;
}

export interface LedgerTotals {
  count: number;
  pretax: string;
  tax: string;
  total: string;
}

export interface LedgerPeriod {
  period: string;
  input: LedgerTotals;
  output: LedgerTotals;
  face_difference_pretax: string;
  face_difference_tax: string;
  taxpayer_types: (TaxpayerType | null)[];
}

export interface LedgerExcluded {
  direction: "input" | "output";
  invoice_number: string;
  invoice_date: string;
  counterpart: string;
  source_files: string[];
  reason: "amount_unrecognized" | "amount_conflict" | "amount_inconsistent";
  message: string;
}

export interface LedgerPayload {
  ok: boolean;
  basis_label: string;
  granularity: "month" | "quarter" | "year";
  periods: LedgerPeriod[];
  totals: { input: LedgerTotals; output: LedgerTotals; face_difference_pretax: string; face_difference_tax: string };
  undated: { input: LedgerTotals; output: LedgerTotals };
  excluded: LedgerExcluded[];
  merged_copies: { input: number; output: number };
  out_of_range: { input: number; output: number };
  warnings: { code: string; message: string }[];
  checks: { code: string; ok: boolean; message: string }[];
  checks_ok: boolean;
  sources: { input: CompanyDirectory; output: CompanyDirectory };
  bank: BankLedger | null;
}

export interface LedgerCheck {
  code: string;
  ok: boolean;
  message: string;
}

/** One account (or all accounts) over one period; null balances mean a month had no statement. */
export interface BankBucket {
  opening: string | null;
  inflow: string;
  outflow: string;
  closing: string | null;
  rows: number;
  missing_months: string[];
  ok: boolean;
}

export interface BankAccount {
  account_no: string;
  account_tail: string;
  account_name: string;
  bank_name: string;
  label: string;
  first_month: string;
  last_month: string;
  statement_files: string[];
  periods: (BankBucket & { period: string })[];
  totals: BankBucket;
}

export interface BankLedger {
  path: string;
  status: string;
  state: "ok" | "no_statements" | "missing_dir" | "unreadable";
  message: string;
  file_count?: number;
  cached?: boolean;
  basis_label?: string;
  accounts?: BankAccount[];
  periods?: { period: string; inflow: string; outflow: string; opening: string | null; closing: string | null; rows: number; complete: boolean }[];
  totals?: { inflow: string; outflow: string; rows: number };
  sources?: { statements: number; receipts: number; unrecognized: { file: string; message: string }[] };
  issues?: { level: "错误" | "警告" | "提示"; code: string; message: string }[];
  checks?: LedgerCheck[];
  checks_ok?: boolean;
}
