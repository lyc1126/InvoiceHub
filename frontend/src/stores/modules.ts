import { defineStore } from "pinia";
import { reactive, ref } from "vue";
import type { ModuleId } from "../modules";
import type { WorkspaceTab } from "./workspace";

export type ModuleSelection = Pick<WorkspaceTab, "companyId" | "dirKey" | "project" | "kind">;

// Runtime view cache only. No business state or URL is persisted to localStorage.
export const useModulesStore = defineStore("module-views", () => {
  const visits = reactive(new Set<string>(["home"]));
  const refresh = reactive<Record<string, number>>({});
  const destinations = reactive<Partial<Record<ModuleId, string>>>({});
  const selections = reactive<Partial<Record<ModuleId, ModuleSelection>>>({});
  const shutdownRequests = ref(0);
  // Set only by the active classic frame's authenticated bridge; App dims the shell with it.
  const modals = reactive<Partial<Record<ModuleId, boolean>>>({});
  // Bookkeeping page head <-> CompanyVouchers (per company): the head shows the selected month
  // and "导出凭证（N）"; the voucher view owns the draft and answers exportTick by opening its
  // own export dialog. Display state only; nothing here is saved.
  const book = reactive<Record<string, { month: string; months: string[]; approved: number; exportable: boolean; exportTick: number }>>({});
  function requestShutdown(): void { shutdownRequests.value += 1; }
  function select(id: ModuleId, selection: ModuleSelection): void { selections[id] = selection; }
  function reload(id: string): void { refresh[id] = (refresh[id] ?? 0) + 1; }
  function open(id: ModuleId, path: string): void {
    destinations[id] = path;
    // Explicit handoffs (e.g. a new inbound batch) are new input, unlike a normal
    // rail switch which must leave the module's existing document and drafts alone.
    reload(id);
  }
  return { visits, refresh, destinations, selections, shutdownRequests, modals, book, requestShutdown, select, reload, open };
});
