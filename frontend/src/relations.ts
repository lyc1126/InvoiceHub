// Folder pairs of one company with a reconciliation relation (WS-07 step 4). The backend
// refuses any other pair; the sidebar and the compare page use this list only to offer
// the pairs it will accept, never to compute anything.
export const RELATIONS = [
  { id: "deduction", label: "成本发票 ⇄ 进项抵扣（勾选清单）", a: "cost_invoice_dir", b: "input_deduction_dir" },
  { id: "inventory", label: "成本发票 ⇄ 开具发票（进销存）", a: "cost_invoice_dir", b: "issued_invoice_dir" },
  { id: "payable", label: "成本发票 ⇄ 银行流水（应付往来）", a: "cost_invoice_dir", b: "bank_flow_dir" },
  { id: "receivable", label: "开具发票 ⇄ 银行流水（应收往来）", a: "issued_invoice_dir", b: "bank_flow_dir" },
] as const;

export type RelationId = (typeof RELATIONS)[number]["id"];

export function relationFor(a: string, b: string) {
  return RELATIONS.find((item) => (item.a === a && item.b === b) || (item.a === b && item.b === a)) ?? null;
}

// Any two invoice folders without a relation, of one company or of two, get the same-number
// check instead (WS-04): invoice numbers on both sides, no amount or counterparty linking.
export const INVOICE_DIRS: readonly string[] = ["cost_invoice_dir", "issued_invoice_dir", "expense_reimbursement_dir"];
export const REFRESHABLE_ROLES: readonly string[] = [...INVOICE_DIRS, "general"];
export const SAME_NUMBER = "same_number";

export function effectiveFolderRole(subdir?: { key: string; role?: string } | null, fallbackKey = ""): string {
  return subdir?.role || subdir?.key || fallbackKey;
}
