// Typed fetch wrapper for the same-origin /api/v1 contract. The backend reports
// failures as {detail} (HTTPException) or {ok:false, message}; both surface as ApiError
// so views can show one diagnosable message instead of a silent empty state.
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
}

const DEFAULT_TIMEOUT_MS = 15_000;

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  options.signal?.addEventListener("abort", () => controller.abort(), { once: true });
  try {
    const response = await fetch(path, {
      method: options.method ?? "GET",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
      credentials: "same-origin",
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(errorMessage(payload) ?? `请求失败（HTTP ${response.status}）`, response.status);
    }
    if (isRecord(payload) && payload.ok === false) {
      throw new ApiError(errorMessage(payload) ?? "请求未完成", response.status);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted) throw new ApiError("请求超时或已取消", 0);
    throw new ApiError("无法连接本机服务", 0);
  } finally {
    clearTimeout(timer);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function errorMessage(payload: unknown): string | undefined {
  if (!isRecord(payload)) return undefined;
  for (const key of ["detail", "message"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return undefined;
}
