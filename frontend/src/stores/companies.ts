import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { ApiError, request } from "../api/client";
import type {
  Company,
  CompanyDeletePayload,
  CompanyFolderCreatePlan,
  CompanyFolderDiscoverPayload,
  CompanyFolderTrashPlan,
  CompanyListPayload,
  CompanyPayload,
  CompanyRefreshState,
  CompanySetupInput,
  CompanySetupJob,
  FolderRole,
  SubdirCreateResult,
  SubdirPlan,
  TaxpayerPeriod,
} from "../api/types";
import { toast } from "../toast";

export interface NewCompany {
  name: string;
  root_dir: string;
  taxpayer_periods: TaxpayerPeriod[];
  subdirs?: Record<string, string>;
  create_missing?: string[];
  plan_hash?: string;
}

export interface CompanyPatch {
  name?: string;
  taxpayer_periods?: TaxpayerPeriod[];
  subdirs?: Record<string, string>;
}

// A source identity, not an object identity: a metadata/status refresh keeps cached views,
// while changing a directory path, role or mapping must invalidate the old results and selection.
export function companySourceKey(company: Company, keys?: string[]): string {
  return JSON.stringify([company.id, company.root_path, keys ?? null, (company.subdirs ?? []).filter((item) => !keys || keys.includes(item.key))
    .map((item) => [item.key, item.relative_path, item.path, item.role ?? item.key]).sort((a, b) => a[0]!.localeCompare(b[0]!))]);
}

// Company registry (WS-07). Every write sends the registry revision this page last read; a
// COMPANY_REVISION_CONFLICT means another page changed the list, so the list is reloaded
// and the user retries on fresh data instead of overwriting someone else's edit.
export const useCompaniesStore = defineStore("companies", () => {
  const list = ref<CompanyListPayload | null>(null);
  const selectedId = ref<string | null>(null);
  const loading = ref(false);
  const error = ref("");
  const refreshStates = ref<Record<string, CompanyRefreshState>>({});
  const refreshTimers = new Map<string, ReturnType<typeof setTimeout>>();
  let generation = 0;

  const companies = computed<Company[]>(() => list.value?.companies ?? []);
  const selected = computed(() => companies.value.find((item) => item.id === selectedId.value) ?? null);

  async function load(): Promise<void> {
    const turn = ++generation;
    loading.value = true;
    error.value = "";
    try {
      const next = await request<CompanyListPayload>("/api/v1/companies");
      if (turn !== generation) return;
      list.value = next;
      if (selectedId.value && !companies.value.some((item) => item.id === selectedId.value)) selectedId.value = null;
      if (!selectedId.value) selectedId.value = list.value.monitored_company_id ?? companies.value[0]?.id ?? null;
    } catch (cause) {
      // Keep the last good list visible; only the banner changes.
      if (turn === generation) error.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      if (turn === generation) loading.value = false;
    }
  }

  async function write<T>(action: (revision: number) => Promise<T>): Promise<T> {
    if (!list.value) await load();
    try {
      return await action(list.value?.revision ?? 0);
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === "COMPANY_REVISION_CONFLICT") {
        await load();
        throw new ApiError("公司清单已被其它页面修改，已刷新，请核对后重试。", cause.status, cause.code);
      }
      throw cause;
    }
  }

  async function create(input: NewCompany): Promise<CompanyPayload> {
    const result = await write((revision) =>
      request<CompanyPayload>("/api/v1/companies", { method: "POST", body: { ...input, revision } }),
    );
    if (!result.company) throw new Error("登记结果待核对，请读取执行结果。");
    selectedId.value = result.company.id;
    await load();
    return result;
  }

  async function update(id: string, patch: CompanyPatch): Promise<CompanyPayload> {
    const result = await write((revision) =>
      request<CompanyPayload>(`/api/v1/companies/${encodeURIComponent(id)}`, { method: "PATCH", body: { ...patch, revision } }),
    );
    await load();
    return result;
  }

  async function remove(id: string): Promise<CompanyDeletePayload> {
    const result = await write((revision) =>
      request<CompanyDeletePayload>(`/api/v1/companies/${encodeURIComponent(id)}?revision=${revision}`, { method: "DELETE" }),
    );
    if (selectedId.value === id) selectedId.value = null;
    await load();
    return result;
  }

  function subdirPlan(id: string, keys?: string[]): Promise<SubdirPlan> {
    const query = keys?.length ? `?keys=${encodeURIComponent(keys.join(","))}` : "";
    return request<SubdirPlan>(`/api/v1/companies/${encodeURIComponent(id)}/subdirs/plan${query}`);
  }

  async function createSubdirs(id: string, planHash: string, keys?: string[]): Promise<SubdirCreateResult> {
    // The plan hash binds what the user confirmed; any change since the preview is a
    // COMPANY_PLAN_STALE error and needs a new preview, never a silent retry.
    const body: Record<string, unknown> = { plan_hash: planHash, confirm: true };
    if (keys?.length) body.keys = keys;
    const result = await request<SubdirCreateResult>(`/api/v1/companies/${encodeURIComponent(id)}/subdirs/create`, {
      method: "POST",
      body,
      acceptPartial: true,
    });
    await load();
    return result;
  }

  function planSetup(input: CompanySetupInput): Promise<CompanySetupJob> {
    return write((revision) => request<CompanySetupJob>("/api/v1/companies/setup-jobs", { method: "POST", body: { ...input, revision } }));
  }

  function getSetup(id: string): Promise<CompanySetupJob> {
    return request<CompanySetupJob>(`/api/v1/companies/setup-jobs/${encodeURIComponent(id)}`);
  }

  function confirmSetup(job: CompanySetupJob): Promise<CompanySetupJob> {
    return request<CompanySetupJob>(`/api/v1/companies/setup-jobs/${encodeURIComponent(job.job_id)}/confirm`, {
      method: "POST", body: { confirm: true, plan_hash: job.plan_hash }, timeoutMs: 60_000,
    });
  }

  async function acceptSetup(job: CompanySetupJob): Promise<void> {
    if (job.state !== "completed" || !job.company) return;
    selectedId.value = job.company.id;
    await load();
  }

  function discoverFolders(companyId: string): Promise<CompanyFolderDiscoverPayload> {
    return request<CompanyFolderDiscoverPayload>(`/api/v1/companies/${encodeURIComponent(companyId)}/folders/discover`);
  }

  function previewCreateFolder(
    companyId: string,
    input: { label: string; relative_path?: string; role: FolderRole },
  ): Promise<CompanyFolderCreatePlan> {
    return write((revision) =>
      request<CompanyFolderCreatePlan>(`/api/v1/companies/${encodeURIComponent(companyId)}/folders/create/preview`, {
        method: "POST",
        body: { ...input, revision },
      }),
    );
  }

  async function createFolder(
    companyId: string,
    input: { label: string; relative_path?: string; role: FolderRole; plan_hash: string },
  ): Promise<CompanyPayload & { folder_id: string }> {
    const result = await write((revision) =>
      request<CompanyPayload & { folder_id: string }>(`/api/v1/companies/${encodeURIComponent(companyId)}/folders/create`, {
        method: "POST",
        body: { ...input, confirm: true, revision },
      }),
    );
    await load();
    return result;
  }

  async function importFolder(
    companyId: string,
    input: { path?: string; relative_path?: string; label?: string; role: FolderRole },
  ): Promise<CompanyPayload & { folder_id: string }> {
    const result = await write((revision) =>
      request<CompanyPayload & { folder_id: string }>(`/api/v1/companies/${encodeURIComponent(companyId)}/folders/import`, {
        method: "POST",
        body: { ...input, revision },
      }),
    );
    await load();
    return result;
  }

  async function updateFolder(
    companyId: string,
    key: string,
    input: { label?: string; role?: FolderRole; rename_disk?: boolean; new_relative_path?: string; new_name?: string },
  ): Promise<CompanyPayload & { disk_renamed?: boolean }> {
    const result = await write((revision) =>
      request<CompanyPayload & { disk_renamed?: boolean }>(
        `/api/v1/companies/${encodeURIComponent(companyId)}/folders/${encodeURIComponent(key)}/update`,
        { method: "POST", body: { ...input, revision } },
      ),
    );
    await load();
    return result;
  }

  async function removeFolder(companyId: string, key: string): Promise<CompanyPayload & { removed_key: string; files_touched: number }> {
    const result = await write((revision) =>
      request<CompanyPayload & { removed_key: string; files_touched: number }>(
        `/api/v1/companies/${encodeURIComponent(companyId)}/folders/${encodeURIComponent(key)}/remove`,
        { method: "POST", body: { revision } },
      ),
    );
    await load();
    return result;
  }

  async function restoreFolder(companyId: string, key: string): Promise<CompanyPayload> {
    const result = await write((revision) =>
      request<CompanyPayload>(
        `/api/v1/companies/${encodeURIComponent(companyId)}/folders/${encodeURIComponent(key)}/restore`,
        { method: "POST", body: { revision } },
      ),
    );
    await load();
    return result;
  }

  function previewTrashFolder(companyId: string, key: string): Promise<CompanyFolderTrashPlan> {
    return write((revision) =>
      request<CompanyFolderTrashPlan>(
        `/api/v1/companies/${encodeURIComponent(companyId)}/folders/${encodeURIComponent(key)}/trash/preview`,
        { method: "POST", body: { revision } },
      ),
    );
  }

  async function trashFolder(
    companyId: string,
    key: string,
    input: { plan_hash: string; also_unregister?: boolean },
  ): Promise<CompanyPayload & { trashed_key: string; unregistered: boolean }> {
    const result = await write((revision) =>
      request<CompanyPayload & { trashed_key: string; unregistered: boolean }>(
        `/api/v1/companies/${encodeURIComponent(companyId)}/folders/${encodeURIComponent(key)}/trash`,
        { method: "POST", body: { ...input, confirm: true, revision }, timeoutMs: 60_000 },
      ),
    );
    await load();
    return result;
  }

  async function promoteFolder(
    companyId: string,
    key: string,
    input: { target_role?: FolderRole; keep_previous_as_custom?: boolean } = {},
  ): Promise<CompanyPayload & { promoted_to: string; preserved_folder_id: string }> {
    const result = await write((revision) =>
      request<CompanyPayload & { promoted_to: string; preserved_folder_id: string }>(
        `/api/v1/companies/${encodeURIComponent(companyId)}/folders/${encodeURIComponent(key)}/promote`,
        { method: "POST", body: { ...input, revision } },
      ),
    );
    await load();
    return result;
  }

  function pickFolderDirectory(): Promise<{ ok: boolean; selected: boolean; path: string }> {
    return request<{ ok: boolean; selected: boolean; path: string }>("/api/v1/companies/pick-directory", {
      method: "POST",
      body: {},
      timeoutMs: 130_000,
    });
  }

  function stopRefreshPoll(companyId: string): void {
    const timer = refreshTimers.get(companyId);
    if (timer !== undefined) {
      clearTimeout(timer);
      refreshTimers.delete(companyId);
    }
  }

  async function pollRefresh(companyId: string, silent: boolean): Promise<void> {
    stopRefreshPoll(companyId);
    try {
      const state = await request<CompanyRefreshState>(`/api/v1/companies/${encodeURIComponent(companyId)}/refresh-data`);
      refreshStates.value = { ...refreshStates.value, [companyId]: state };
      if (state.status === "running") {
        refreshTimers.set(companyId, setTimeout(() => void pollRefresh(companyId, silent), 600));
        return;
      }
      window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId } }));
      if (!silent && state.message) toast(state.message, state.status === "failed" ? "error" : "info", 3600);
    } catch {
      stopRefreshPoll(companyId);
    }
  }

  async function refreshData(
    companyId: string,
    options: { keys?: string[]; force?: boolean; silent?: boolean } = {},
  ): Promise<CompanyRefreshState | null> {
    stopRefreshPoll(companyId);
    const body: Record<string, unknown> = {};
    if (options.keys?.length) body.keys = options.keys;
    if (options.force) body.force = true;
    try {
      const state = await request<CompanyRefreshState>(`/api/v1/companies/${encodeURIComponent(companyId)}/refresh-data`, {
        method: "POST",
        body,
      });
      refreshStates.value = { ...refreshStates.value, [companyId]: state };
      if (state.status === "running") {
        refreshTimers.set(companyId, setTimeout(() => void pollRefresh(companyId, Boolean(options.silent)), 500));
      } else {
        window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId } }));
        if (!options.silent && state.message) toast(state.message, state.status === "failed" ? "error" : "info", 3600);
      }
      return state;
    } catch (cause) {
      if (!options.silent) toast(`无法读取数据：${cause instanceof Error ? cause.message : String(cause)}`, "error", 4000);
      return null;
    }
  }

  return {
    planSetup, getSetup, confirmSetup, acceptSetup,
    list, companies, selected, selectedId, loading, error, refreshStates,
    load, create, update, remove, subdirPlan, createSubdirs, refreshData,
    discoverFolders, previewCreateFolder, createFolder, importFolder,
    updateFolder, removeFolder, restoreFolder, previewTrashFolder, trashFolder,
    promoteFolder, pickFolderDirectory,
  };
});
