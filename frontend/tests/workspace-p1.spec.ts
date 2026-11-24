import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import CompanyCreateForm from "../src/components/CompanyCreateForm.vue";
import CompanyVouchers from "../src/components/CompanyVouchers.vue";
import { useCompaniesStore } from "../src/stores/companies";
import type { Company } from "../src/api/types";
const company = { id: "co_test", subdirs: [] } as unknown as Company;
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

it("keeps a lost registration response query-only with the selected empty folders", async () => {
  const pinia = createPinia(); setActivePinia(pinia);
  useCompaniesStore().list = { revision: 3, standard_subdirs: [], companies: [] } as never;
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, body: JSON.parse(String(init.body || "{}")) });
    if (url.endsWith("/detect")) return response({ root_status: "present", plan_hash: "h1", subdirs: [{ key: "bank_flow_dir", label: "银行流水", status: "missing", suggested_action: "create", file_count: null }] });
    if (url.includes("registration-jobs")) return response({ state: "unknown", message: "登记结果待核对" });
    return response({ detail: "synthetic lost response" }, 503);
  }));
  const wrapper = mount(CompanyCreateForm, { global: { plugins: [pinia] } });
  await wrapper.get('[aria-label="公司资料夹"]').setValue("/synthetic");
  await wrapper.get('input[value="later"]').setValue(true);
  await new Promise(resolve => setTimeout(resolve, 350)); await flushPromises();
  await wrapper.get('input[type="checkbox"]').setValue(true);
  await wrapper.get("form").trigger("submit"); await flushPromises();
  expect(calls.find(call => call.url === "/api/v1/companies")!.body.create_missing).toEqual(["bank_flow_dir"]);
  await wrapper.get("form").trigger("submit");
  await wrapper.findAll("button").find(b => b.text() === "读取登记结果")!.trigger("click"); await flushPromises();
  expect(calls.filter(call => call.url === "/api/v1/companies")).toHaveLength(1);
  expect(wrapper.text()).toContain("登记结果待核对"); wrapper.unmount();
});

it("uses the indexed selected month and only queries a lost export response", async () => {
  const pinia = createPinia(); setActivePinia(pinia);
  const months = ["2026-05", "2026-06"].map(month => ({ month, vouchers: 1, approved: 1, blocked: 0, exported: 0 }));
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const body = JSON.parse(String(init.body || "{}")); calls.push(`${init.method || "GET"} ${url}`);
    if (url.endsWith("/voucher-drafts")) return response({ drafts: [{ name: "凭证草稿_test.xlsx", months }], months });
    if (url.includes("/export-jobs/")) return response({ state: "unknown", message: "导出结果待核对" });
    if (url.endsWith("/export")) {
      expect(body.month).toBe("2026-06");
      return body.dry_run ? response({ columns: ["借方"], unmatched: [], sample_rows: [["0.30"]], months: [] }) : response({ detail: "synthetic interruption" }, 503);
    }
    return response({ name: "凭证草稿_test.xlsx", revision: "r1", months, vouchers: [], approved: 1, blocked: 0 });
  }));
  const wrapper = mount(CompanyVouchers, { props: { company }, global: { plugins: [pinia] }, attachTo: document.body });
  await flushPromises();
  await wrapper.get('select[aria-label="月份"]').setValue("2026-06");
  await wrapper.findAll("button").find(b => b.text() === "导出已审核…")!.trigger("click");
  const input = document.querySelector<HTMLInputElement>('[aria-label="制单人"]')!;
  input.value = "合成"; input.dispatchEvent(new Event("input", { bubbles: true }));
  await new Promise(resolve => setTimeout(resolve, 350)); await flushPromises();
  (Array.from(document.querySelectorAll("button")).find(b => b.textContent === "确认导出")!).click(); await flushPromises();
  const confirm = Array.from(document.querySelectorAll("button")).find(b => b.textContent === "确认导出")!;
  expect(confirm.disabled).toBe(true);
  (Array.from(document.querySelectorAll("button")).find(b => b.textContent === "读取导出结果")!).click(); await flushPromises();
  expect(calls.filter(call => call.startsWith("POST") && call.endsWith("/export"))).toHaveLength(2); // preview + one execution
  expect(document.body.textContent).toContain("导出结果待核对"); wrapper.unmount();
});

it("releases the export button only when the receipt says the server rejected before writing", async () => {
  const pinia = createPinia(); setActivePinia(pinia);
  const months = [{ month: "2026-06", vouchers: 1, approved: 1, blocked: 0, exported: 0 }];
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const body = JSON.parse(String(init.body || "{}")); calls.push(`${init.method || "GET"} ${url}`);
    if (url.endsWith("/voucher-drafts")) return response({ drafts: [{ name: "凭证草稿_test.xlsx", months }], months });
    if (url.includes("/export-jobs/")) return response({ state: "rejected", message: "未导出：账套不可用" });
    if (url.endsWith("/export")) return body.dry_run ? response({ columns: ["借方"], unmatched: [], sample_rows: [], months: [] })
      : response({ error: { code: "VOUCHER_DRAFT_BOOKS_UNAVAILABLE", message: "账套不可用" } }, 409);
    return response({ name: "凭证草稿_test.xlsx", revision: "r1", months, vouchers: [], approved: 1, blocked: 0 });
  }));
  const wrapper = mount(CompanyVouchers, { props: { company }, global: { plugins: [pinia] }, attachTo: document.body });
  await flushPromises();
  await wrapper.findAll("button").find(b => b.text() === "导出已审核…")!.trigger("click");
  const input = document.querySelector<HTMLInputElement>('[aria-label="制单人"]')!;
  input.value = "合成"; input.dispatchEvent(new Event("input", { bubbles: true }));
  await new Promise(resolve => setTimeout(resolve, 350)); await flushPromises();
  (Array.from(document.querySelectorAll("button")).find(b => b.textContent === "确认导出")!).click(); await flushPromises();
  expect(calls.filter(call => call.startsWith("GET") && call.includes("/export-jobs/"))).toHaveLength(1);
  expect(Array.from(document.querySelectorAll("button")).some(b => b.textContent === "读取导出结果")).toBe(false);
  expect(document.body.textContent).toContain("未导出：账套不可用"); wrapper.unmount();
});

it("re-detects after a failed registration instead of locking the wizard", async () => {
  const pinia = createPinia(); setActivePinia(pinia);
  useCompaniesStore().list = { revision: 3, standard_subdirs: [], companies: [] } as never;
  let detects = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/detect")) { detects += 1; return response({ root_status: "present", plan_hash: `h${detects}`, subdirs: [] }); }
    if (url.includes("registration-jobs")) return response({ state: "failed", message: "创建中止：OSError；已创建目录保留。" });
    return response({ state: "failed", created: [], message: "创建中止" });
  }));
  const wrapper = mount(CompanyCreateForm, { global: { plugins: [pinia] } });
  await wrapper.get('[aria-label="公司资料夹"]').setValue("/synthetic");
  await wrapper.get('input[value="later"]').setValue(true);
  await new Promise(resolve => setTimeout(resolve, 350)); await flushPromises();
  await wrapper.get("form").trigger("submit"); await flushPromises();
  await wrapper.findAll("button").find(b => b.text() === "读取登记结果")!.trigger("click"); await flushPromises();
  await new Promise(resolve => setTimeout(resolve, 10)); await flushPromises();
  expect(detects).toBe(2);
  expect(wrapper.findAll("button").some(b => b.text() === "读取登记结果")).toBe(false);
  expect(wrapper.text()).toContain("已重新检测"); wrapper.unmount();
});

it("renders company tax identity read-only, keeps the output rate editable and labels fallback in the embedded cost page", () => {
  const script = readFileSync("../web/static/js/page-costs.js", "utf8");
  const typeLabel = { hidden: false };
  const rateLabel = { hidden: false };
  const select = (label: { hidden: boolean }) => ({ disabled: false, value: "", closest: () => label });
  const refs = { taxpayerTypeSelect: select(typeLabel), outputTaxRateSelect: select(rateLabel), taxProfileReadonly: { hidden: true, textContent: "" }, saveTaxProfileBtn: { hidden: false } };
  const state = { taxProfileEditing: true, payload: { reference_tax_profile: { taxpayer_source: "company_registry", company_name: "合成甲", taxpayer_type_label: "小规模纳税人", output_tax_rate_display: "3%" } } };
  const context = vm.createContext({ refs, state, URLSearchParams, location: { search: "?workspace_embed=1" }, setText: (node: { textContent: string }, text: string) => { node.textContent = text; }, updateTaxProfileControls() {} });
  vm.runInContext(script.slice(script.indexOf("function renderTaxProfile()"), script.indexOf("function updateTaxProfileControls()")), context);
  context.renderTaxProfile();
  expect(refs.taxpayerTypeSelect.disabled && typeLabel.hidden).toBe(true);
  // 2026-11-10 decision: only the identity is locked; the cost page still edits the output rate.
  expect(refs.outputTaxRateSelect.disabled || rateLabel.hidden || refs.saveTaxProfileBtn.hidden).toBe(false);
  expect(refs.taxProfileReadonly.textContent).toBe("合成甲 · 小规模纳税人");
  state.payload.reference_tax_profile.taxpayer_source = "saved";
  context.renderTaxProfile(); expect(refs.taxProfileReadonly.textContent).toContain("未设置，按");
});
