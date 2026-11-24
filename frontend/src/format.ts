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
  stale: "有变动",
  never_built: "未读取",
  unknown: "待确认",
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

// Headline figures follow the prototype: ≥ 10,000 reads as "22.56 万" (half-up, at most two
// decimals); smaller values keep the exact grouped amount. Integer cents keep it float-free.
export function wan(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return value;
  const [, sign = "", integer = "", fraction = ""] = match;
  if (BigInt(integer) < 10000n) return money(value);
  const cents = BigInt(integer + fraction.padEnd(2, "0").slice(0, 2));
  const hundredths = (cents + 5000n) / 10000n;
  const text = `${hundredths / 100n}.${String(hundredths % 100n).padStart(2, "0")}`.replace(/\.?0+$/, "");
  return `${sign}${text} 万`;
}

// Projection rates arrive as decimal fractions ("0.13"); show them as the prototype's "13%".
// Anything else (empty, "免税", already "13%") is shown as-is rather than guessed.
export function ratePercent(value: string | null | undefined): string {
  if (!value) return "—";
  if (!/^(0(\.\d+)?|1(\.0+)?)$/.test(value.trim())) return value;
  return `${Math.round(Number(value) * 10000) / 100}%`;
}

export function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}
