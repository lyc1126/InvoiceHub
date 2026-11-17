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
