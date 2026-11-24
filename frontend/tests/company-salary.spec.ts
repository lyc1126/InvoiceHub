import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import CompanySalary from "../src/components/CompanySalary.vue";
import type { Company } from "../src/api/types";

const company = { id: "co_salary", root_path: "/合成公司", subdirs: [{ key: "payroll_social_dir", relative_path: "工资社保", path: "/合成公司/工资社保", status: "present" }] } as Company;
const row = { name: "甲*丙", id_number: "TEST****1234", gross: "100.00", deductions: "20.00", net: "80.00", social: "20.00", fund: "0.00", tax: "0.00", other: "0.00", expense_path: "" };
const entry = { candidate_id: "opaque-candidate", month: "2026-08", source: "工资.xlsx", headcount: 1, rows: [row], totals: { gross: "100.00", deductions: "20.00", net: "80.00" }, needs_expense_path: true };
const payload = () => ({ candidates: [structuredClone(entry)], confirmed: {}, files: [], source_revision: "source1", tax_revision: "tax1", tax_file: true, current_month: "2026-11" });
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const options = () => ({ props: { company, month: "2026-08" }, global: { stubs: { teleport: true } } });
const button = (wrapper: ReturnType<typeof mount>, text: string) => wrapper.findAll("button").find(item => item.text() === text)!;
const confirm = async (wrapper: ReturnType<typeof mount>) => {
  await button(wrapper, "确认工资计提…").trigger("click");
  await wrapper.get('[aria-label="工资计提费用科目路径"]').setValue("管理费用/工资");
  await button(wrapper, "确认写入工资明细").trigger("click");
  await flushPromises();
};
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("explicit salary confirmation", () => {
  it("shows masked source rows and posts only candidate identity, revision and explicit expense path", async () => {
    const calls: { method: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit = {}) => {
      calls.push({ method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined });
      return response(init.method === "PUT" ? { ok: true } : payload());
    }));
    const wrapper = mount(CompanySalary, options());
    await flushPromises();
    expect(wrapper.text()).toContain("甲*丙");
    await button(wrapper, "确认工资计提…").trigger("click");
    expect(button(wrapper, "确认写入工资明细").attributes("disabled")).toBeDefined();
    await button(wrapper, "取消").trigger("click");
    expect(calls.filter(call => call.method === "PUT")).toHaveLength(0);
    await confirm(wrapper);
    expect(calls.filter(call => call.method === "PUT")).toEqual([{ method: "PUT", body: {
      revision: "tax1", source_revision: "source1", month: "2026-08", candidate_id: "opaque-candidate", expense_path: "管理费用/工资",
    } }]);
    expect(wrapper.emitted("saved")).toHaveLength(1);
    wrapper.unmount();
  });

  it("refreshes a conflict once and never replays the write", async () => {
    let reads = 0, writes = 0;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit = {}) => {
      if (init.method === "PUT") { writes++; return response({ message: "工资原表已变化", error: { code: "SALARY_CONFLICT" } }, 409); }
      reads++; return response(payload());
    }));
    const wrapper = mount(CompanySalary, options());
    await flushPromises();
    await confirm(wrapper);
    expect(reads).toBe(2);
    expect(writes).toBe(1);
    expect(wrapper.text()).toContain("工资原表已变化");
    wrapper.unmount();
  });

  it("locks an unknown write until a successful read, including a failed read-back", async () => {
    let failRead = false, writes = 0;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit = {}) => {
      if (init.method === "PUT") { writes++; return response({}, 503); }
      return response(failRead ? {} : payload(), failRead ? 503 : 200);
    }));
    const wrapper = mount(CompanySalary, options());
    await flushPromises();
    await confirm(wrapper);
    expect(wrapper.text()).toContain("不会自动重发");
    expect(button(wrapper, "确认工资计提…").attributes("disabled")).toBeDefined();
    failRead = true;
    await button(wrapper, "读取确认结果").trigger("click"); await flushPromises();
    expect(button(wrapper, "确认工资计提…").attributes("disabled")).toBeDefined();
    failRead = false;
    await button(wrapper, "读取确认结果").trigger("click"); await flushPromises();
    expect(button(wrapper, "确认工资计提…").attributes("disabled")).toBeUndefined();
    expect(writes).toBe(1);
    wrapper.unmount();
  });

  it("drops late company responses, refreshes a shared revision and paginates fifty rows", async () => {
    let finish!: (value: Response) => void;
    const pending = new Promise<Response>(resolve => { finish = resolve; });
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      if (++calls === 1) return pending;
      const data = payload();
      data.candidates[0]!.rows = Array.from({ length: 51 }, (_, i) => ({ ...row, name: `合成${i}` }));
      return response(data);
    }));
    const wrapper = mount(CompanySalary, { ...options(), props: { company, taxRevision: "first" } });
    await wrapper.setProps({ company: { ...company, id: "co_other" } }); await flushPromises();
    finish(response({ ...payload(), candidates: [{ ...entry, source: "迟到旧公司.xlsx" }] })); await flushPromises();
    expect(wrapper.text()).not.toContain("迟到旧公司");
    expect(wrapper.findAll("tbody tr")).toHaveLength(50);
    await button(wrapper, "下一页").trigger("click");
    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
    await wrapper.setProps({ taxRevision: "social-confirmed" }); await flushPromises();
    expect(calls).toBe(3);
    wrapper.unmount();
  });

  it("keeps future months disabled and removes confirmation with the shared revision", async () => {
    const data = payload();
    data.candidates[0]!.month = "2027-01";
    const confirmed = { ...entry, source_current: false };
    const calls: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit = {}) => {
      if (init.method === "PUT") calls.push(JSON.parse(String(init.body)));
      return response({ ...data, confirmed: { "2026-08": confirmed } });
    }));
    const wrapper = mount(CompanySalary, options()); await flushPromises();
    expect(button(wrapper, "确认工资计提…").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("原表已变更或不可读");
    await button(wrapper, "取消工资确认").trigger("click"); await flushPromises();
    expect(calls).toEqual([{ revision: "tax1", month: "2026-08", remove: true }]);
    wrapper.unmount();
  });

  it("hides revealed personnel immediately when a masked reload fails", async () => {
    let fail = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const data = payload();
      if (url.endsWith("reveal=true")) data.candidates[0]!.rows[0]!.name = "合成完整姓名";
      return response(fail ? {} : data, fail ? 503 : 200);
    }));
    const wrapper = mount(CompanySalary, options()); await flushPromises();
    await wrapper.get('input[type="checkbox"]').setValue(true); await flushPromises();
    expect(wrapper.text()).toContain("合成完整姓名");
    fail = true;
    await wrapper.get('input[type="checkbox"]').setValue(false); await flushPromises();
    expect(wrapper.text()).not.toContain("合成完整姓名");
    expect(wrapper.find("tbody").exists()).toBe(false);
    wrapper.unmount();
  });
});
