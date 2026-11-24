import { request } from "./client";
import type { PreviewRef } from "./types";

export interface PreviewJob {
  job_id: string; keep_alive_url: string; idle_timeout_seconds: number; initial_page?: number;
  files: { file_number: number; name: string; preview_type: string; page_count: number;
    reason: string; page_url_template: string; text_url: string }[];
}

// Receipt capabilities have a separate, company-bound API; never send them through the
// active-invoice selector, which must continue to reject non-monitored invoice identities.
export function createPreviewJob<T = PreviewJob>(preview: PreviewRef, signal?: AbortSignal): Promise<T> {
  const url = "kind" in preview && preview.kind === "receipt"
    ? `/api/v1/companies/${encodeURIComponent(preview.company_id)}/receipt-preview-jobs`
    : "/api/v1/invoices/preview-jobs";
  return request<T>(url, { method: "POST", body: preview, timeoutMs: 60_000, signal });
}
