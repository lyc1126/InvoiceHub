import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { afterEach, expect, it, vi } from "vitest";
import CompanyVouchers from "../src/components/CompanyVouchers.vue";
import CompanyInventoryResult from "../src/components/CompanyInventoryResult.vue";
import CompanyPayroll from "../src/components/CompanyPayroll.vue";
import BankLayouts from "../src/components/BankLayouts.vue";
import CompanyTax from "../src/components/CompanyTax.vue";
import type { Company, CompareResult } from "../src/api/types";
const company = { id: "co_synthetic", root_path: "synthetic", subdirs: [] } as unknown as Company;
const response = (body: unknown) => new Response(JSON.stringify(body));
const name = "凭证草稿_2026-06_2026-06.xlsx";
const line = (row: number) => ({ row, summary: "合成分录", code: "1002", name: "银行存款", debit: row === 2 ? "10.10" : null, credit: row === 3 ? "10.10" : null, supplier: "", qty: null, unit: "", todo: "", basis: "", confidence: "" });
const draft = { name, revision: "r1", approved: 1, blocked: 0, books_error: "", vouchers: [{ month: "2026-06", number: "001", date: "2026-06-30", approval: "通过", debit_total: "10.10", credit_total: "10.10", errors: [], warnings: [], lines: [line(2), line(3)] }] };
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

it("sends structural edits and keeps a failed unknown-result query locked", async () => {
  let puts = 0, lost = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    if (init.method === "PUT") { puts++; lost = true; throw Error("lost"); }
    if (url.endsWith("/voucher-drafts")) return response({ drafts: [{ name }], months: [] });
    if (lost) throw Error("query failed");
    return response(draft);
  }));
  const wrapper = mount(CompanyVouchers, { props: { company }, global: { plugins: [createPinia()] } }); await flushPromises();
  await wrapper.findAll("button").find(b => b.text() === "加一行")!.trigger("click");
  await wrapper.get('[aria-label="第 -1 行借方"]').setValue("0.20");
  await wrapper.get('[aria-label="删除第 2 行"]').trigger("click");
  expect(wrapper.get("tfoot").text()).toContain("0.20");
  expect(wrapper.get("tfoot").text()).toContain("借贷不平");
  await wrapper.findAll("button").find(b => b.text().startsWith("保存（"))!.trigger("click"); await flushPromises();
  const sent = JSON.parse(String(vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "PUT")![1]!.body));
  expect(sent.vouchers[0].delete_rows).toEqual([2]);
  expect(sent.vouchers[0].add_lines[0]).toMatchObject({ row: -1, debit: "0.20" });
  await wrapper.findAll("button").find(b => b.text() === "查询审核表")!.trigger("click"); await flushPromises();
  expect(wrapper.findAll("button").find(b => b.text().startsWith("保存（"))!.attributes("disabled")).toBeDefined();
  expect(wrapper.get('[aria-label="第 -1 行借方"]').attributes("disabled")).toBeDefined();
  expect(puts).toBe(1); wrapper.unmount();
});

it("requires revalidation after typing a fixed account and limits mapping actions to unknown files", async () => {
  let fixed = "";
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    if (url.endsWith("/preview")) { fixed = JSON.parse(String(init.body)).account_fixed ?? ""; return response({ columns: ["日期", "收入", "支出", "余额"], fields: [], guessed_mapping: {}, revision: 0, layout_hash: "h", account_fixed: fixed, balance_chain: { ok: true, breaks: [] }, save_blockers: fixed ? [] : ["缺账号"] }); }
    const recognition = (kind: string) => ({ kind, rows: 3, chain_ok: true, breaks: [], footer: { ok: null, message: "未提供" }, message: "" });
    return response({ revision: 0, layouts: {}, files: ["builtin", "confirmed", "unrecognized"].map(kind => ({ name: kind, file_ref: kind, recognition: recognition(kind) })) });
  }));
  const wrapper = mount(BankLayouts, { props: { company }, attachTo: document.body }); await flushPromises();
  expect(wrapper.findAll("button").filter(b => b.text() === "确认列映射")).toHaveLength(1);
  await wrapper.findAll("button").find(b => b.text() === "确认列映射")!.trigger("click"); await flushPromises();
  const account = document.querySelector<HTMLInputElement>('[aria-label="手填本方账号"]')!;
  account.value = "001234"; account.dispatchEvent(new Event("input", { bubbles: true })); await flushPromises();
  const button = (label: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent === label)!;
  expect(button("确认并保存为版式档案").disabled).toBe(true);
  button("校验映射").click(); await flushPromises();
  expect(fixed).toBe("001234"); expect(button("确认并保存为版式档案").disabled).toBe(false); wrapper.unmount();
});

it("keeps backend inventory numbers and exception evidence in the compact view", async () => {
  const item = { key: "s", name: "合成材料", unit: "吨", open_qty: "1", in_qty: "2", out_qty: "4", end_qty: "-1", end_amount: "-12.34", oversold: true, sold_never_bought: false, months: [], specs: [] };
  const wrapper = mount(CompanyInventoryResult, { props: { compact: true, result: { items: [item], totals: { end_amount: "-12.34" } } as unknown as CompareResult } });
  expect(wrapper.get('[aria-label="库存精简视图"]').text()).toContain("-12.34");
  expect(wrapper.text()).toContain("卖超");
  await wrapper.findAll("button").find(b => b.text() === "查看明细")!.trigger("click");
  expect(wrapper.find('[aria-label="进销存"]').exists()).toBe(true); wrapper.unmount();
});

it("highlights the selected social-insurance period without inventing wages", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ folder: "工资社保", folder_present: true, files: [], confirmed: {}, people: [], months: ["2026-05", "2026-06"].map(month => ({ month, rows: [], checks_ok: true, unit_total: "0.00", personal_total: "0.00", total: "0.00" })) })));
  const wrapper = mount(CompanyPayroll, { props: { company, month: "2026-06" } }); await flushPromises();
  expect(wrapper.findAll(".payroll-current")).toHaveLength(1);
  expect(wrapper.get(".payroll-current").text()).toContain("2026-06");
  await wrapper.setProps({ month: "2026-05" }); expect(wrapper.get(".payroll-current").text()).toContain("2026-05"); wrapper.unmount();
});
