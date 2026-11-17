import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { ApiError, request } from "../api/client";
import type {
  Company,
  CompanyDeletePayload,
  CompanyListPayload,
  CompanyPayload,
  CompanySetupInput,
  CompanySetupJob,
  SubdirCreateResult,
  SubdirPlan,
  TaxpayerPeriod,
} from "../api/types";

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
// while changing a directory mapping must invalidate the old results and selection.
export function companySourceKey(company: Company, keys?: string[]): string {
  return JSON.stringify([company.id, company.root_path, keys ?? null, (company.subdirs ?? []).filter((item) => !keys || keys.includes(item.key))
    .map((item) => [item.key, item.relative_path]).sort((a, b) => a[0]!.localeCompare(b[0]!))]);
}

// Company registry (WS-07). Every write sends the registry revision this page last read; a
// COMPANY_REVISION_CONFLICT means another page changed the list, so the list is reloaded
// and the user retries on fresh data instead of overwriting someone else's edit.
export const useCompaniesStore = defineStore("companies", () => {
  const list = ref<CompanyListPayload | null>(null);
  const selectedId = ref<string | null>(null);
  const loading = ref(false);
  const error = ref("");
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

  function subdirPlan(id: string): Promise<SubdirPlan> {
    return request<SubdirPlan>(`/api/v1/companies/${encodeURIComponent(id)}/subdirs/plan`);
  }

  async function createSubdirs(id: string, planHash: string): Promise<SubdirCreateResult> {
    // The plan hash binds what the user confirmed; any change since the preview is a
    // COMPANY_PLAN_STALE error and needs a new preview, never a silent retry.
    const result = await request<SubdirCreateResult>(`/api/v1/companies/${encodeURIComponent(id)}/subdirs/create`, {
      method: "POST",
      body: { plan_hash: planHash, confirm: true },
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

  return { planSetup, getSetup, confirmSetup, acceptSetup, list, companies, selected, selectedId, loading, error, load, create, update, remove, subdirPlan, createSubdirs };
});
