import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

// Home module of the workspace shell (WS-01): which objects are open as tabs, what is pinned in
// the sidebar, the sidebar width and the folder picked for a comparison. Tabs only exist here;
// other modules keep their own state. Pins, width and expanded companies are UI preferences of
// this browser profile (localStorage), never business data: losing them changes no amount.

export type TabKind = "company" | "directory" | "project" | "compare" | "new-company" | "tags" | "server-dir";

export interface WorkspaceTab {
  id: string;
  kind: TabKind;
  companyId?: string;
  dirKey?: string;
  project?: string;
  relation?: string;
  // Same-number check (WS-04): the second folder, possibly of another company.
  otherCompanyId?: string;
  otherDirKey?: string;
  // Read-only server directory view (WS-09 Option A).
  sourceId?: string;
  parentId?: string;
  sourceLabel?: string;
  dirLabel?: string;
  // Bumped by a double click on "hi.": the tab's view is rebuilt and reloads, other tabs keep theirs.
  refresh: number;
}

export interface CompareBase {
  companyId: string;
  dirKey: string;
}

export type InvoiceColumnKey =
  | "seller"
  | "buyer"
  | "format"
  | "invoice_number"
  | "project"
  | "classification"
  | "tax_rate"
  | "amount"
  | "invoice_date"
  | "status";

export const INVOICE_COLUMN_KEYS: readonly InvoiceColumnKey[] = [
  "seller",
  "buyer",
  "format",
  "invoice_number",
  "project",
  "classification",
  "tax_rate",
  "amount",
  "invoice_date",
  "status",
];
const INVOICE_COLUMN_SET = new Set<string>(INVOICE_COLUMN_KEYS);

export const SIDEBAR_DEFAULT = 292;
export const SIDEBAR_MIN = 220;
export const SIDEBAR_MAX = 460;
// The content area keeps at least this much room next to the sidebar.
export const CONTENT_MIN = 620;
const STORAGE_KEY = "invoicehub.workspace.v1";

interface Saved {
  pins?: unknown;
  sidebarWidth?: unknown;
  expanded?: unknown;
  hiddenInvoiceColumns?: unknown;
}

function readSaved(): Saved {
  try {
    const value = JSON.parse(globalThis.localStorage?.getItem(STORAGE_KEY) ?? "{}");
    return value && typeof value === "object" ? (value as Saved) : {};
  } catch {
    return {};
  }
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function hiddenColumnsMap(value: unknown): Record<string, InvoiceColumnKey[]> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result: Record<string, InvoiceColumnKey[]> = {};
  for (const [dirKey, raw] of Object.entries(value as Record<string, unknown>)) {
    if (!dirKey || !Array.isArray(raw)) continue;
    const cleaned = [...new Set(raw.filter((item): item is InvoiceColumnKey => typeof item === "string" && INVOICE_COLUMN_SET.has(item)))];
    if (cleaned.length) result[dirKey] = cleaned;
  }
  return result;
}

export function tabId(tab: Omit<WorkspaceTab, "id" | "refresh">): string {
  if (tab.kind === "server-dir") {
    return ["server-dir", tab.sourceId ?? "", tab.parentId ?? ""].join(":");
  }
  const parts = [tab.kind, tab.companyId ?? "", tab.dirKey ?? "", tab.project ?? "", tab.relation ?? ""];
  if (tab.otherCompanyId || tab.otherDirKey) parts.push(tab.otherCompanyId ?? "", tab.otherDirKey ?? "");
  return parts.join(":");
}

/** Width the sidebar may take in a window of `viewport` px next to a rail of `rail` px. */
export function clampSidebar(width: number, viewport: number, rail: number): { width: number; limited: "" | "min" | "max" } {
  const max = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, viewport - rail - CONTENT_MIN));
  if (width <= SIDEBAR_MIN) return { width: SIDEBAR_MIN, limited: "min" };
  if (width >= max) return { width: max, limited: "max" };
  return { width: Math.round(width), limited: "" };
}

export const useWorkspaceStore = defineStore("workspace", () => {
  const saved = readSaved();
  const tabs = ref<WorkspaceTab[]>([]);
  const activeId = ref<string | null>(null);
  const pins = ref<string[]>(stringList(saved.pins));
  const expanded = ref<string[]>(stringList(saved.expanded));
  const sidebarWidth = ref(typeof saved.sidebarWidth === "number" ? saved.sidebarWidth : SIDEBAR_DEFAULT);
  // Per-directory-type hidden invoice columns (e.g. hiding 购买方 in 成本发票 without hiding it
  // in 开具发票). Pure UI preference stored in localStorage alongside pins/width.
  const hiddenInvoiceColumns = ref<Record<string, InvoiceColumnKey[]>>(hiddenColumnsMap(saved.hiddenInvoiceColumns));
  const compareBase = ref<CompareBase | null>(null);
  // The first visit opens the monitored company once; after the user closes every tab the
  // start page stays empty instead of reopening it.
  const seeded = ref(false);
  // Prototype openWizard(): adding a company folder is a dialog over the current view, not a tab.
  const createOpen = ref(false);

  const active = computed(() => tabs.value.find((tab) => tab.id === activeId.value) ?? null);

  watch(
    [pins, expanded, sidebarWidth, hiddenInvoiceColumns],
    () => {
      try {
        globalThis.localStorage?.setItem(
          STORAGE_KEY,
          JSON.stringify({
            pins: pins.value,
            expanded: expanded.value,
            sidebarWidth: sidebarWidth.value,
            hiddenInvoiceColumns: hiddenInvoiceColumns.value,
          }),
        );
      } catch {
        // Private mode or a full quota: the preference just does not survive a reload.
      }
    },
    { deep: true },
  );

  function open(spec: Omit<WorkspaceTab, "id" | "refresh">): WorkspaceTab {
    const id = tabId(spec);
    let tab = tabs.value.find((item) => item.id === id);
    if (!tab) {
      tab = { ...spec, id, refresh: 0 };
      const index = tabs.value.findIndex((item) => item.id === activeId.value);
      tabs.value.splice(index < 0 ? tabs.value.length : index + 1, 0, tab);
    }
    activeId.value = id;
    seeded.value = true;
    return tab;
  }

  function close(id: string): void {
    const index = tabs.value.findIndex((tab) => tab.id === id);
    if (index < 0) return;
    tabs.value.splice(index, 1);
    if (activeId.value === id) activeId.value = (tabs.value[index] ?? tabs.value[index - 1])?.id ?? null;
  }

  function closeCompany(companyId: string): void {
    for (const tab of tabs.value.filter((item) => item.companyId === companyId || item.otherCompanyId === companyId)) close(tab.id);
    pins.value = pins.value.filter((pin) => pin.split(":")[1] !== companyId);
    if (compareBase.value?.companyId === companyId) compareBase.value = null;
  }

  function closeDirectory(companyId: string, dirKey: string): void {
    // Close the directory tab itself plus any same-number comparison tab referencing it;
    // sidebar pins use the `dir:` prefix while workspace tabs use `tabId({ kind: "directory", ... })`.
    for (const tab of tabs.value.filter(
      (item) =>
        (item.companyId === companyId && item.dirKey === dirKey)
        || (item.otherCompanyId === companyId && item.otherDirKey === dirKey),
    )) {
      close(tab.id);
    }
    pins.value = pins.value.filter((pin) => pin !== `dir:${companyId}:${dirKey}`);
    if (compareBase.value?.companyId === companyId && compareBase.value.dirKey === dirKey) {
      compareBase.value = null;
    }
  }

  function refreshActive(): void {
    if (active.value) active.value.refresh += 1;
  }

  function togglePin(node: string): void {
    pins.value = pins.value.includes(node) ? pins.value.filter((pin) => pin !== node) : [...pins.value, node];
  }

  function toggleExpanded(companyId: string): void {
    expanded.value = expanded.value.includes(companyId)
      ? expanded.value.filter((id) => id !== companyId)
      : [...expanded.value, companyId];
  }

  function hiddenColumnsFor(dirKey: string, availableColumns: readonly InvoiceColumnKey[]): InvoiceColumnKey[] {
    const stored = (hiddenInvoiceColumns.value[dirKey] ?? []).filter((key) => availableColumns.includes(key));
    // Guard against corrupted/stale localStorage hiding every available column.
    if (availableColumns.length > 0 && stored.length >= availableColumns.length) return [];
    return stored;
  }

  function toggleInvoiceColumn(
    dirKey: string,
    column: InvoiceColumnKey,
    availableColumns: readonly InvoiceColumnKey[],
  ): boolean {
    if (!availableColumns.includes(column)) return false;
    const current = hiddenColumnsFor(dirKey, availableColumns);
    const nextMap = { ...hiddenInvoiceColumns.value };
    if (current.includes(column)) {
      const next = current.filter((item) => item !== column);
      if (next.length) nextMap[dirKey] = next;
      else delete nextMap[dirKey];
      hiddenInvoiceColumns.value = nextMap;
      return true;
    }
    // Never allow hiding the last remaining data column.
    if (availableColumns.length - current.length <= 1) return false;
    nextMap[dirKey] = [...current, column];
    hiddenInvoiceColumns.value = nextMap;
    return true;
  }

  function resetInvoiceColumns(dirKey: string): void {
    if (!hiddenInvoiceColumns.value[dirKey]?.length) return;
    const nextMap = { ...hiddenInvoiceColumns.value };
    delete nextMap[dirKey];
    hiddenInvoiceColumns.value = nextMap;
  }

  return {
    tabs, activeId, active, pins, expanded, sidebarWidth, hiddenInvoiceColumns, compareBase, seeded, createOpen,
    open, close, closeCompany, closeDirectory, refreshActive, togglePin, toggleExpanded,
    hiddenColumnsFor, toggleInvoiceColumn, resetInvoiceColumns,
  };
});
