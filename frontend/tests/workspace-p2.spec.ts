import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, expect, it, vi } from "vitest";
import InvoiceTagsEditor from "../src/components/InvoiceTagsEditor.vue";
import OverviewDocuments from "../src/components/OverviewDocuments.vue";
import BankLayouts from "../src/components/BankLayouts.vue";
import CompanyTax from "../src/components/CompanyTax.vue";
import type { Company } from "../src/api/types";
const company = { id: "co_test", root_path: "synthetic", subdirs: [] } as unknown as Company;
const response = (body: unknown) => new Response(JSON.stringify(body));
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });
const button = (label: string) => Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find(b => b.textContent === label)!;

it("shows known usage and unavailable companies", async () => {
  const pinia = createPinia(); setActivePinia(pinia);
  vi.stubGlobal("fetch", vi.fn(async () => response({ revision: 1, tags: [{ id: "tag_a", name: "待核对", meaning: "", color: "#ef4444" }], usage: { tag_a: 2 }, usage_complete: false, usage_unavailable: [{ id: "co_off", name: "离线公司" }] })));
  const wrapper = mount(InvoiceTagsEditor, { global: { plugins: [pinia] } }); await flushPromises();
  expect(wrapper.text()).toContain("已知 2 张"); expect(wrapper.text()).toContain("离线公司");
  expect(vi.mocked(fetch).mock.calls[0]![0]).toContain("include_usage=1"); wrapper.unmount();
});

it("renders server match states and manual projects", async () => {
  vi.stubGlobal("IntersectionObserver", undefined);
  vi.stubGlobal("fetch", vi.fn(async () => response({ state: "ok", records: { a: [
    { id: "1", invoice_number: "1", flow_match: "matched", project: "工程甲", project_source: "manual" },
    { id: "2", invoice_number: "2", flow_match: "unmatched" }, { id: "3", invoice_number: "3", flow_match: null },
  ] }, receipts: [] })));
  const wrapper = mount(OverviewDocuments, { props: { company, start: "", end: "", active: true } }); await flushPromises();
  expect(wrapper.findAll(".pill-ok")).toHaveLength(2);
  expect(wrapper.text()).toContain("工程甲（人工）"); expect(wrapper.findAll(".overview-doc .tag")).toHaveLength(4); wrapper.unmount();
});

it("revalidates mapping changes and queries lost saves without reposting", async () => {
  const calls: string[] = [];
  const preview = { columns: ["日期", "账号", "收入", "支出", "余额"], fields: ["date", "account", "inflow", "outflow", "balance"], guessed_mapping: { date: 0, account: 1, inflow: 2, outflow: 3, balance: 4 }, layout_hash: "h", revision: 0, balance_chain: { ok: true, breaks: [] } };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push(`${init.method || "GET"} ${url}`);
    if (url.endsWith("/preview")) return response(preview);
    if (init.method === "POST") throw new Error("lost reply");
    return response({ revision: 0, files: [{ file_ref: "opaque", name: "合成.csv" }], layouts: {} });
  }));
  const wrapper = mount(BankLayouts, { props: { company }, attachTo: document.body }); await flushPromises();
  button("确认列映射").click(); await flushPromises();
  const select = document.querySelector<HTMLSelectElement>('[aria-label="收入 映射"]')!;
  select.value = ""; select.dispatchEvent(new Event("change", { bubbles: true })); await flushPromises();
  expect(button("确认并保存为版式档案").disabled).toBe(true);
  button("校验映射").click(); await flushPromises(); button("确认并保存为版式档案").click(); await flushPromises();
  expect(button("确认并保存为版式档案").disabled).toBe(true);
  button("查询保存结果").click(); await flushPromises();
  expect(calls.filter(call => call.startsWith("POST") && !call.endsWith("/preview"))).toHaveLength(1);
  expect(document.body.textContent).toContain("不会重复提交"); wrapper.unmount();
});

it("blocks saving a valid chain when the server reports a save blocker", async () => {
  const preview = { columns: ["日期", "收入", "支出", "余额"], fields: ["date", "account", "inflow", "outflow", "balance"], guessed_mapping: { date: 0, inflow: 1, outflow: 2, balance: 3 }, layout_hash: "h", revision: 0, profile_applied: false, save_blockers: ["必须指定账号列，且一份对账单只含一个账号。"], sample_rows: [{ row: 2, values: ["2026-06-01", "1.00", "", "1.00"] }], balance_chain: { ok: true, direction: { reverse: false, sign: 1 }, breaks: [] } };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url.endsWith("/preview") ? preview : { revision: 0, files: [{ file_ref: "opaque", name: "合成.csv" }], layouts: {} })));
  const wrapper = mount(BankLayouts, { props: { company }, attachTo: document.body }); await flushPromises();
  button("确认列映射").click(); await flushPromises();
  expect(document.body.textContent).toContain("余额链全部成立"); expect(document.body.textContent).toContain("必须指定账号列");
  expect(document.querySelectorAll(".map-table .chip")).toHaveLength(4);
  expect(button("确认并保存为版式档案").disabled).toBe(true); wrapper.unmount();
});

it("expands a tax row trace and names missing records", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ revision: 1, start: "2026-06", end: "2026-06", totals: { estimated: "10.00", declared: null, paid: null }, limitations: [], rows: [
    { month: "2026-06", tax_type: "vat", label: "增值税", declared: null, paid: null, source: "", assessment: null, estimate: { amount: "10.00", closing_credit: "0.00", explanation: "合成解释", blockers: [], algorithm_id: "alg", steps: [] } },
    { month: "2026-06", tax_type: "stamp", label: "印花税", declared: null, paid: null, source: "", assessment: null, estimate: { amount: null, closing_credit: null, explanation: "未计算", blockers: [{ code: "TAX_RULE_UNVERIFIED", message: "规则未复核" }], algorithm_id: null, steps: [] } },
  ] })));
  const wrapper = mount(CompanyTax, { props: { company, start: "2026-06", end: "2026-06" }, attachTo: document.body }); await flushPromises();
  expect(wrapper.text()).toContain("待申报"); expect(wrapper.text()).toContain("规则待复核");
  expect(wrapper.text()).not.toContain("合成解释");
  await wrapper.find("tr.row-link").trigger("click"); expect(wrapper.text()).toContain("合成解释"); wrapper.unmount();
});

it("keeps missing tax unknown and a lost write query-only", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push(`${init.method || "GET"} ${url}`); if (init.method === "PUT") throw new Error("lost reply");
    return response({ revision: 0, totals: { estimated: null, declared: null, paid: null }, rows: [], limitations: [] });
  }));
  const wrapper = mount(CompanyTax, { props: { company, start: "2026-06", end: "2026-06" }, attachTo: document.body }); await flushPromises();
  expect(wrapper.findAll(".overview-vat strong").map(el => el.text())).toEqual(["未测算", "未录入", "未录入"]);
  button("录入申报结果").click(); await flushPromises();
  expect(document.querySelector<HTMLInputElement>('[aria-label="已申报"]')!.value).toBe("");
  document.querySelector<HTMLFormElement>("[role=dialog] form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); await flushPromises();
  expect(button("确认保存").disabled).toBe(true);
  button("查询保存结果").click(); await flushPromises(); expect(calls.filter(call => call.startsWith("PUT"))).toHaveLength(1); wrapper.unmount();
});

it("does not confirm a lost tax save with different assumptions", async () => {
  let saved = false, matching = false, puts = 0;
  const base = { revision: 0, start: "2026-06", end: "2026-06", totals: { estimated: null, declared: null, paid: null }, rows: [], limitations: [] };
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit = {}) => {
    if (init.method === "PUT") { puts++; saved = true; throw new Error("lost reply"); }
    return response(!saved ? base : { ...base, revision: 1, rows: [{ month: "2026-06", label: "增值税", estimate: { amount: null, closing_credit: null, blockers: [], steps: [], explanation: "合成" }, tax_type: "vat", declared: "0.00", paid: null, source: "合成表", assessment: { output_tax: matching ? "100.00" : "200.00", input_tax: "0.00", transfer_out: "0.00", opening_credit: "0.00", ordinary_only: true, source_kind: "user_assumption" } }] });
  }));
  const wrapper = mount(CompanyTax, { props: { company, start: "2026-06", end: "2026-06" }, attachTo: document.body }); await flushPromises();
  button("录入申报结果").click(); await flushPromises();
  const set = (label: string, value: string) => { const input = document.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!; input.value = value; input.dispatchEvent(new Event("input", { bubbles: true })); };
  set("已申报", "0"); set("税额来源", "合成表");
  document.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(); await flushPromises();
  set("本月销项税额", "100"); set("本月已确认进项税额", "0"); set("本月转出进项税额", "0"); set("已核对上期留抵", "0");
  document.querySelector<HTMLFormElement>("[role=dialog] form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); await flushPromises();
  button("查询保存结果").click(); await flushPromises();
  expect(document.body.textContent).toContain("不会重复保存");
  matching = true; button("查询保存结果").click(); await flushPromises();
  expect(document.body.textContent).toContain("已查询到保存的记录"); expect(puts).toBe(1); wrapper.unmount();
});
