import type { InjectionKey, Ref } from "vue";

export const MODULES = [
  { id: "costs", path: "/costs", label: "成本分析", icon: "costs" },
  { id: "documents", path: "/documents", label: "单据", icon: "docs" },
  { id: "bookkeeping", path: "/bookkeeping", label: "做账", icon: "book" },
  { id: "ocr", path: "/ocr", label: "OCR", icon: "ocr" },
  { id: "consistency", path: "/consistency", label: "一致性", icon: "check" },
  { id: "settings", path: "/settings", label: "设置", icon: "gear" },
] as const;
export type ModuleId = typeof MODULES[number]["id"];
export const VIEW_ACTIVE: InjectionKey<Readonly<Ref<boolean>>> = Symbol("workspace-view-active");
export const MODULE_CHANNEL = "invoicehub.workspace.v1";

export function moduleForPath(path: string) {
  return MODULES.find((item) => item.path === path);
}

export function workspaceDestination(href: string): string | null {
  let url: URL;
  try { url = new URL(href, location.href); } catch { return null; }
  if (url.origin !== location.origin || url.username || url.password) return null;
  if (url.pathname !== "/" && !moduleForPath(url.pathname)) return null;
  url.searchParams.delete("workspace_embed");
  url.searchParams.delete("workspace_view");
  return `${url.pathname}${url.search}${url.hash}`;
}

export function frameLocation(path: string, recovery: boolean): string {
  const url = new URL(path, location.href);
  const allowed = moduleForPath(url.pathname) || url.pathname === "/skins" || /^\/invoices\/[^/]+$/.test(url.pathname);
  if (url.origin !== location.origin || url.username || url.password || !allowed) throw new Error("模块页面地址无效");
  url.searchParams.set("workspace_embed", "1");
  if (recovery) url.searchParams.set("no_skin", "1");
  return `${url.pathname}${url.search}${url.hash}`;
}
