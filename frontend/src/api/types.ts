import type { CompareFocus, RecordIds } from "../compareFocus";
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
  root_status: "present" | "missing" | "not_directory" | "outside_root" | "unreadable";
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
  standard_subdirs?: { key: string; label: string }[];
  revision: number;
  companies: Company[];
  monitored_company_id: string | null;
  target_id: string;
  watch_dir: string;
}

export interface CompanySetupInput {
  name: string;
  parent_dir: string;
  folder_name: string;
  subdirs: Record<string, string>;
  taxpayer_periods: TaxpayerPeriod[];
}

export interface CompanySetupJob {
  ok: boolean;
  job_id: string;
  state: "prepared" | "unknown" | "completed" | "failed";
  plan_hash: string;
  root_path: string;
  name: string;
  items: { key: string; label: string; relative_path: string }[];
  created: string[];
  in_progress: string;
  message: string;
  company: Company | null;
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
  /** Present for the monitored folder's rows; selection actions send it back with invoice_key. */
  source_path?: string;
  /** WS-06 tag ids in definition order; display data only. */
  tags?: string[];
  source_file: string;
  file_format: string;
  invoice_type: string;
  business_type?: string;
  classification_issue?: string;
  invoice_number: string;
  invoice_date: string;
  seller: string;
  buyer: string;
  amount: string;
  tax_rate: string;
  status: string;
}

export interface InvoiceListStats { total: number; recognized: number; needs_review: number; duplicates: number; total_amount: string | number; total_amount_valid_count?: number; total_amount_missing_count?: number; total_amount_conflict_count?: number }

export interface DirectoryInvoicesPayload {
  ok: boolean;
  count: number;
  items: InvoiceRow[];
  page?: number;
  page_size?: number;
  read_only: boolean;
  directory: CompanyDirectory;
  tags_error?: string;
  /** Full-folder and fully filtered statistics, including tags, before pagination. */
  stats?: { all?: InvoiceListStats; filtered?: InvoiceListStats };
  /** A first, still-building result: rows may move, so nothing can be selected (classic homepage rule). */
  snapshot?: { provisional?: boolean; revision?: string };
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
  accounts?: { state: string; source: string; month: string; message: string; items: {
    code: string; name: string; opening: string; debit: string; credit: string; closing: string;
  }[] };
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

/** One 用途确认信息 row as the backend returns it; amounts are decimal strings. */
export interface DeductionRow {
  invoice_number: string;
  invoice_code: string;
  status: string;
  invoice_date: string;
  seller: string;
  period: string;
  file: string;
  金额: string | null;
  税额: string | null;
  有效抵扣税额: string | null;
}

export interface DeductionMatched extends DeductionRow {
  timing: "current" | "carried" | "after_period" | "unknown";
  invoice_month: string | null;
  invoice_tax: string | null;
  tax_ok: boolean;
  source_files: string[];
}

export interface DeductionUnlisted {
  invoice_number: string;
  invoice_date: string;
  seller: string;
  invoice_type: string;
  tax: string | null;
  later_list_periods: string[];
  source_files: string[];
}

export interface InventoryMonth {
  month: string;
  open_qty: string; open_amount: string; in_qty: string; in_amount: string;
  out_qty: string; cost: string; end_qty: string; end_amount: string;
  unit_price: string | null;
  note: string;
  steps?: string[];
}

// One spec under a category: purchases and sales only; opening stock and cost stay on the category.
export interface InventorySpec {
  key: string;
  name: string; spec: string; unit: string;
  in_qty: string; in_amount: string; out_qty: string; net_qty: string;
  record_ids?: RecordIds;
}

export interface InventoryItem {
  key: string;
  name: string; unit: string;
  account_code: string;
  open_qty: string; open_amount: string; in_qty: string; in_amount: string;
  out_qty: string; cost: string; end_qty: string; end_amount: string;
  oversold: boolean;
  sold_never_bought: boolean;
  months: InventoryMonth[];
  specs: InventorySpec[];
  record_ids?: RecordIds;
}

export interface InventoryOpeningEntry {
  code: string; account: string; family: string; unit: string; qty: string; amount: string; reason?: string;
}

export interface InventoryOpening {
  source: "ledger" | "zero";
  month: string;
  read_months: string[];
  files: string[];
  items: InventoryOpeningEntry[];
  unassigned: InventoryOpeningEntry[];
  error: string;
}

export interface SettlementInvoice {
  invoice_number: string;
  invoice_date: string;
  total: string;
  source_files: string[];
}

export interface SettlementFlow {
  row_id: string;
  date: string;
  month: string;
  counterparty: string;
  details: string;
  amount: string;
  file: string;
  reason?: string;
  name_match?: string;
}

export interface SettlementParty {
  name: string;
  opening: string; invoiced: string; settled: string; closing: string;
  invoice_count: number; flow_count: number;
  unpaid: SettlementInvoice[];
  unallocated: SettlementFlow[];
  record_ids?: RecordIds;
  steps?: string[];
}

/** One row of a side-by-side source list (WS-04): an invoice, a statement row or a list row. */
// Monitored folder only (WS-04): the homepage identities preview-jobs re-validates.
export interface InvoicePreviewRef {
  target_id: string;
  items: { invoice_key: string; source_path: string }[];
}

export interface ReceiptPreviewRef {
  kind: "receipt"; company_id: string; receipt_id: string; token: string; page: number;
}
export type PreviewRef = InvoicePreviewRef | ReceiptPreviewRef;

export interface CompareRecord {
  flow_match?: "matched" | "unmatched" | null;
  project?: string | null;
  project_source?: "remark" | "manual" | null;
  id: string;
  preview?: PreviewRef;
  invoice_number: string;
  invoice_date: string;
  counterpart: string;
  amount: string;
  source_file: string;
  details?: string;
  detail?: CompareFocus;
}

// WS-04 same-number check: two invoice folders without a relation, possibly of two companies.
export interface SameNumberFamily {
  number: string; invoice_date: string; seller: string; buyer: string; counterpart: string;
  total: string | null; amount_issue: "" | "conflict" | "unrecognized"; formats: string[]; source_files: string[];
}
export interface SameNumberMatch {
  number: string; kind: "duplicate" | "pair"; amount_differs: boolean; party_differs: boolean;
  a: SameNumberFamily; b: SameNumberFamily; record_ids: RecordIds; steps: string[];
}
export interface SameNumberSide { company_id: string; company_name: string; key: string; label: string; source: { status: string } }
export interface SameNumberResult {
  ok: boolean; relation: "same_number"; state: "ok" | "no_details" | "missing_dir"; message: string;
  sides: { a: SameNumberSide; b: SameNumberSide };
  basis_label?: string; matches?: SameNumberMatch[];
  counts?: { a_invoices: number; b_invoices: number; a_unnumbered: number; b_unnumbered: number; matched: number; duplicate: number; pair: number; amount_differs: number };
  records?: { a: CompareRecord[]; b: CompareRecord[] };
  checks?: LedgerCheck[]; checks_ok?: boolean; warnings?: { code: string; message: string }[];
}

export interface CompareResult {
  ok: boolean;
  relation: "deduction" | "inventory" | "settlement";
  state: "ok" | "no_lists" | "no_details" | "no_statements" | "missing_dir" | "unreadable";
  message: string;
  basis_label?: string;
  periods?: {
    period: string; list_rows: number; matched_current: number; matched_carried: number; matched_other: number;
    list_only: number; not_selected: number; deductible_tax: string;
    record_ids?: RecordIds; steps?: string[];
  }[];
  lists?: { file: string; period: string; rows: number; selected: number; in_range: boolean }[];
  matched?: DeductionMatched[];
  list_only?: DeductionRow[];
  not_selected?: DeductionRow[];
  duplicates?: { invoice_number: string; periods: string[]; files: string[] }[];
  not_listed?: { special: DeductionUnlisted[]; ordinary: number; unknown_type: DeductionUnlisted[] };
  unrecognized?: { file: string; message: string }[];
  warnings?: { code: string; message: string }[];
  checks?: LedgerCheck[];
  checks_ok?: boolean;
  // inventory
  first_month?: string | null;
  cost_label?: string;
  items?: InventoryItem[];
  opening?: InventoryOpening;
  excluded?: { direction: "input" | "output"; invoice_number: string; invoice_date: string; name: string; spec: string; unit: string; quantity: string; amount: string; source_file: string; reason: string }[];
  totals?: { open_amount?: string; in_amount?: string; cost?: string; end_amount?: string; opening?: string; invoiced?: string; settled?: string; closing?: string };
  // settlement
  summary_details?: (CompareFocus & { value: string })[];
  receipts?: CompareRecord[];
  side?: "payable" | "receivable";
  side_label?: string;
  parties?: SettlementParty[];
  matches?: { kind: "one_to_one" | "combination"; basis: string; flow: SettlementFlow; invoices: SettlementInvoice[]; record_ids?: RecordIds }[];
  records?: { a: CompareRecord[]; b: CompareRecord[] };
  red_offsets?: { red: SettlementInvoice; blue: SettlementInvoice }[];
  red_unmatched?: SettlementInvoice[];
  non_invoice_flows?: SettlementFlow[];
  ambiguous_flows?: SettlementFlow[];
  excluded_invoices?: { invoice_number: string; invoice_date: string; party: string; reason: string; source_files: string[] }[];
}

export interface ProjectInvoice {
  direction: "input" | "output";
  invoice_number: string;
  invoice_date: string;
  counterpart: string;
  total: string;
  project: string;
  source: "remark" | "manual" | "conflict" | "none";
  remark_projects: string[];
  assignable: boolean;
  source_files: string[];
}

export interface ProjectSummary {
  ok: boolean;
  basis_label: string;
  assignments_revision: number;
  projects: {
    project: string;
    unassigned: boolean;
    input: LedgerTotals;
    output: LedgerTotals;
    face_difference_pretax: string;
    periods: { period: string; input_pretax: string; output_pretax: string }[];
  }[];
  project_names: string[];
  unassigned_invoices: ProjectInvoice[];
  manual_invoices: ProjectInvoice[];
  warnings: { code: string; message: string }[];
  checks: LedgerCheck[];
  checks_ok: boolean;
}

export interface InvoiceTag {
  id: string;
  name: string;
  color: string;
  meaning: string;
}

export interface InvoiceTagDefinitions {
  usage?: Record<string, number>;
  usage_unavailable?: { id: string; name: string }[];
  usage_complete?: boolean;
  ok: boolean;
  revision: number;
  tags: InvoiceTag[];
  purged_companies?: number;
  purge_failed?: string[];
}

export interface InvoiceTagMarks {
  ok: boolean;
  revision: number;
  invoices: Record<string, string[]>;
}

// Appearance is shared with the classic pages; the workspace stores no separate preference.
export interface Skin {
  id: string;
  stylesheet_url: string;
}

export interface SkinsPayload {
  ok: boolean;
  enabled_skin_id: string | null;
  active_skin: Skin | null;
  skins: Skin[];
}

export interface CompanyDetection {
  root_status: SubdirStatus;
  subdirs: { key: string; label: string; relative_path: string; status: SubdirStatus; path: string; file_count: number | null; suggested_action: string; candidates?: string[]; selection_required?: boolean }[];
  plan_hash: string;
}

export interface CompanyRefreshDirStatus {
  status: "pending" | "running" | "done" | "skipped_missing" | "skipped_active" | "failed" | "cancelled";
  label: string;
  count: number;
  error: string;
}

export interface CompanyRefreshState {
  ok?: boolean;
  company_id: string;
  job_id: string;
  status: "idle" | "running" | "completed" | "failed";
  keys: string[];
  current_key: string;
  current_label: string;
  message: string;
  directories: Record<string, CompanyRefreshDirStatus>;
  updated_at: string;
}
