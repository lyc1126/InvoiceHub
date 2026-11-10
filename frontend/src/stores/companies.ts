import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { ApiError, request } from "../api/client";
import type {
  Company,
  CompanyDeletePayload,
  CompanyListPayload,
  CompanyPayload,
  SubdirCreateResult,
  SubdirPlan,
  TaxpayerPeriod,
} from "../api/types";

export interface NewCompany {
  name: string;
  root_dir: string;
  taxpayer_periods: TaxpayerPeriod[];
}

// Company registry (WS-07). Every write sends the registry revision this page last read; a
// COMPANY_REVISION_CONFLICT means another page changed the list, so the list is reloaded
// and the user retries on fresh data instead of overwriting someone else's edit.
export const useCompaniesStore = defineStore("companies", () => {
  const list = ref<CompanyListPayload | null>(null);
  const selectedId = ref<string | null>(null);
  const loading = ref(false);
  const error = ref("");

  const companies = computed<Company[]>(() => list.value?.companies ?? []);
  const selected = computed(() => companies.value.find((item) => item.id === selectedId.value) ?? null);

  async function load(): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      list.value = await request<CompanyListPayload>("/api/v1/companies");
      if (selectedId.value && !companies.value.some((item) => item.id === selectedId.value)) selectedId.value = null;
      if (!selectedId.value) selectedId.value = list.value.monitored_company_id ?? companies.value[0]?.id ?? null;
    } catch (cause) {
      // Keep the last good list visible; only the banner changes.
      error.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
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
    selectedId.value = result.company.id;
    await load();
    return result;
  }

  async function update(id: string, patch: Partial<Pick<Company, "name" | "taxpayer_periods">>): Promise<CompanyPayload> {
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

  return { list, companies, selected, selectedId, loading, error, load, create, update, remove, subdirPlan, createSubdirs };
});
