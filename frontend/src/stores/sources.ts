import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { request } from "../api/client";
import { errorText } from "../format";

export interface ServerSourceProgress {
  phase: string;
  completed?: number;
  total?: number;
  enumerated?: number;
  bytes?: number;
  total_bytes?: number;
  downloaded?: number;
}

export interface ServerSource {
  id: string;
  name: string;
  protocol: "mounted" | "sftp";
  root: string;
  revision: number;
  connection: string;
  sync: string;
  error: string;
  error_code?: string;
  task_id: string;
  fingerprints: string[];
  fingerprint?: string;
  generation: string;
  snapshot: string;
  last_complete_at: string;
  last_verified_at?: string;
  coverage: string;
  entry_count: number;
  cached_count: number;
  cache_budget: number;
  summarized_scopes?: string[];
  binding?: { company_id: string; role: string } | null;
  progress?: ServerSourceProgress;
}

export interface MountedShare {
  name: string;
  path: string;
  remote: string;
  fs_type: string;
}

export interface ServerEntry {
  id: string;
  name: string;
  relative: string;
  kind: "file" | "directory";
  size: number;
  cached?: boolean;
}

export interface ServerBreadcrumb {
  id: string;
  name: string;
}

export interface ServerListing {
  source: ServerSource;
  items: ServerEntry[];
  count: number;
  page: number;
  breadcrumbs: ServerBreadcrumb[];
  scope: { files: number; bytes: number; readable_files?: number };
}

export interface ServerInvoiceRow {
  entry_id: string;
  invoice_key: string;
  relative: string;
  source_path: string;
  source_file: string;
  file_format: string;
  invoice_number: string;
  invoice_type: string;
  business_type: string;
  classification_status: string;
  classification_issue: string;
  tax_rate: string;
  invoice_date: string;
  amount: string;
  tax_amount: string;
  pretax_amount: string;
  seller: string;
  buyer: string;
  duplicate: boolean;
  status: string;
  cached?: boolean;
}

export interface ServerInvoiceStatsBucket {
  total: number;
  recognized: number;
  needs_review: number;
  duplicates: number;
  total_amount: string;
  total_amount_valid_count: number;
  total_amount_missing_count: number;
  total_amount_conflict_count: number;
}

export interface ServerSummaryPayload {
  available: boolean;
  message?: string;
  generation?: string;
  source_generation?: string;
  last_complete_at?: string;
  stale?: boolean;
  items?: ServerInvoiceRow[];
  count?: number;
  total_count?: number;
  page?: number;
  page_size?: number;
  breadcrumbs?: ServerBreadcrumb[];
  scope_parent_id?: string;
  scope_name?: string;
  invoice_stats?: {
    all: ServerInvoiceStatsBucket;
    filtered: ServerInvoiceStatsBucket;
  };
  cost_failed_count?: number;
  cost_error?: string;
  ledger?: { totals: { input: { count: number; total: string; pretax: string; tax: string } } };
  scope?: string;
  stats?: { parsed: number; reused: number };
}

export interface ServerPreviewFile {
  file_number: number;
  entry_id: string;
  name: string;
  preview_type: string;
  page_count: number;
  reason: string;
  stale: boolean;
  verified_at: string;
  page_url_template: string;
  text_url: string;
}

export interface ServerPreviewJob {
  job_id: string;
  preview_type: string;
  page_count: number;
  reason: string;
  stale: boolean;
  verified_at: string;
  source_id: string;
  entry_id: string;
  record_count?: number;
  idle_timeout_seconds?: number;
  keep_alive_url?: string;
  files?: ServerPreviewFile[];
}

export const RUNNING_SYNC_STATES = new Set(["connecting", "scanning", "downloading", "parsing", "publishing"]);

export const PHASE_LABELS: Record<string, string> = {
  connecting: "正在连接",
  scanning: "正在核对目录",
  downloading: "正在校验下载",
  parsing: "正在解析",
  publishing: "正在发布",
  idle: "就绪",
  failed: "失败",
  cancelled: "已取消",
};

export const CONNECTION_LABELS: Record<string, string> = {
  online: "已连接",
  offline: "离线",
  connecting: "连接中",
  auth_required: "需要认证",
  host_key_changed: "主机指纹变化",
  root_changed: "根目录身份变化",
};

export function isSourceRunning(source?: ServerSource | null): boolean {
  return !!source && RUNNING_SYNC_STATES.has(source.sync);
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 ** 2).toFixed(1)} MiB`;
}

export const useSourcesStore = defineStore("sources", () => {
  const sources = ref<ServerSource[]>([]);
  const mountedShares = ref<MountedShare[]>([]);
  const selectedId = ref("");
  const loadError = ref("");
  const loading = ref(false);
  const sharesLoading = ref(false);
  // Incremented when any source finishes a scan/summary/download/config update so open workspace tabs reload.
  const revisionTick = ref(0);

  const selected = computed(() => sources.value.find((item) => item.id === selectedId.value) ?? null);

  function byId(id: string): ServerSource | null {
    return sources.value.find((item) => item.id === id) ?? null;
  }

  function upsert(value: ServerSource): void {
    const index = sources.value.findIndex((item) => item.id === value.id);
    if (index < 0) sources.value.push(value);
    else sources.value[index] = value;
  }

  function remove(id: string): void {
    sources.value = sources.value.filter((item) => item.id !== id);
    if (selectedId.value === id) selectedId.value = sources.value[0]?.id ?? "";
    revisionTick.value += 1;
  }

  function notifyUpdated(): void {
    revisionTick.value += 1;
  }

  async function load(): Promise<ServerSource[]> {
    loading.value = true;
    loadError.value = "";
    try {
      const data = await request<{ sources: ServerSource[]; error?: string }>("/api/v1/sources");
      sources.value = data.sources ?? [];
      if (data.error) loadError.value = data.error;
      if (selectedId.value && !sources.value.some((item) => item.id === selectedId.value)) {
        selectedId.value = sources.value[0]?.id ?? "";
      } else if (!selectedId.value && sources.value[0]) {
        selectedId.value = sources.value[0].id;
      }
      return sources.value;
    } catch (cause) {
      loadError.value = errorText(cause);
      return sources.value;
    } finally {
      loading.value = false;
    }
  }

  async function loadMountedShares(): Promise<MountedShare[]> {
    sharesLoading.value = true;
    try {
      const data = await request<{ shares?: MountedShare[] }>("/api/v1/sources/mounted-shares");
      mountedShares.value = data.shares ?? [];
      return mountedShares.value;
    } catch {
      mountedShares.value = [];
      return [];
    } finally {
      sharesLoading.value = false;
    }
  }

  return {
    sources,
    mountedShares,
    selectedId,
    selected,
    loadError,
    loading,
    sharesLoading,
    revisionTick,
    byId,
    upsert,
    remove,
    notifyUpdated,
    load,
    loadMountedShares,
  };
});
