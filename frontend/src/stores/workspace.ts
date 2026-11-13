import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

// Home module of the workspace shell (WS-01): which objects are open as tabs, what is pinned in
// the sidebar, the sidebar width and the folder picked for a comparison. Tabs only exist here;
// other modules keep their own state. Pins, width and expanded companies are UI preferences of
// this browser profile (localStorage), never business data: losing them changes no amount.

export type TabKind = "company" | "directory" | "project" | "compare" | "new-company" | "tags";

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
  // Bumped by a double click on "hi.": the tab's view is rebuilt and reloads, other tabs keep theirs.
  refresh: number;
}

export interface CompareBase {
  companyId: string;
  dirKey: string;
}

export const SIDEBAR_DEFAULT = 280;
export const SIDEBAR_MIN = 220;
export const SIDEBAR_MAX = 460;
// The content area keeps at least this much room next to the sidebar.
export const CONTENT_MIN = 620;
const STORAGE_KEY = "invoicehub.workspace.v1";

interface Saved {
  pins?: unknown;
  sidebarWidth?: unknown;
  expanded?: unknown;
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

export function tabId(tab: Omit<WorkspaceTab, "id" | "refresh">): string {
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
  const compareBase = ref<CompareBase | null>(null);
  // The first visit opens the monitored company once; after the user closes every tab the
  // start page stays empty instead of reopening it.
  const seeded = ref(false);

  const active = computed(() => tabs.value.find((tab) => tab.id === activeId.value) ?? null);

  watch(
    [pins, expanded, sidebarWidth],
    () => {
      try {
        globalThis.localStorage?.setItem(
          STORAGE_KEY,
          JSON.stringify({ pins: pins.value, expanded: expanded.value, sidebarWidth: sidebarWidth.value }),
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

  return {
    tabs, activeId, active, pins, expanded, sidebarWidth, compareBase, seeded,
    open, close, closeCompany, refreshActive, togglePin, toggleExpanded,
  };
});
