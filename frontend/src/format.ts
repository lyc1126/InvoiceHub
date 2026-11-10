import type { FreshnessState, SubdirStatus, TaxpayerType } from "./api/types";

export const TAXPAYER_LABELS: Record<TaxpayerType, string> = { general: "一般纳税人", small_scale: "小规模纳税人" };

export function taxpayerLabel(value: TaxpayerType | null | undefined): string {
  return value ? TAXPAYER_LABELS[value] : "未设置";
}

export const SUBDIR_STATUS_LABELS: Record<SubdirStatus, string> = {
  present: "已有",
  missing: "缺失",
  not_directory: "同名文件占用",
  outside_root: "链接或越出资料夹",
  unreadable: "无法读取",
  root_unavailable: "资料夹不可用",
};

export const FRESHNESS_LABELS: Record<FreshnessState, string> = {
  monitored: "监控中",
  fresh: "最新",
  stale: "已过期",
  never_built: "未汇总",
  unknown: "无法确认",
  missing_dir: "目录缺失",
  not_checked: "未检查",
};

// Money arrives as exact decimal strings from the backend; group digits on the string so no
// value passes through a float on its way to the screen.
export function money(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(value);
  if (!match) return value;
  const [, sign = "", integer = "", fraction = ""] = match;
  return `${sign}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}`;
}

export function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}
