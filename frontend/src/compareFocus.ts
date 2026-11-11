import type { InjectionKey } from "vue";

// WS-04: a clicked category (stock category, spec, counterparty, matched payment, deduction
// period) hands its source record ids and the backend's calculation steps to the compare
// page, which opens the detail drawer and narrows the side-by-side source lists.
export interface RecordIds {
  a: string[];
  b: string[];
}

export interface CompareFocus {
  label: string;
  record_ids: RecordIds;
  steps: string[];
}

export const COMPARE_FOCUS: InjectionKey<(focus: CompareFocus) => void> = Symbol("compareFocus");
