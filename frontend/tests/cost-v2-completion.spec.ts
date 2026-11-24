import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, expect, it, vi } from "vitest";
import type { Component } from "vue";
import CostAnalysis from "../src/components/CostAnalysis.vue";
import CostItemTypes from "../src/components/CostItemTypes.vue";
import CostServiceCosts from "../src/components/CostServiceCosts.vue";
import CostInventorySetup from "../src/components/CostInventorySetup.vue";
import type { Company } from "../src/api/types";

const company = { id: "co_completion", name: "合成公司", root_path: "/合成公司", subdirs: [] } as unknown as Company;
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const button = (wrapper: ReturnType<typeof mount>, text: string) => wrapper.findAll("button").find(node => node.text() === text)!;
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.innerHTML = ""; });

it("keeps zero service costs distinct from absent costs and exposes both sources", async () => {
  const service = (project: string, cost: string | null) => ({ month: "2026-07", project, revenue: "1000.00", cost,
    gross_profit: cost === null ? null : "1000.00", gross_margin_percent: cost === null ? null : "100", state: cost === null ? "needs_review" : "known",
    reasons: cost === null ? ["未录入成本"] : [], sources: [{ date: "2026-07-03", invoice_number: "0011", source_file: "service.xml" }],
    cost_sources: cost === null ? [] : [{ id: "zero", source: "已核实零成本", amount: "0.00" }] });
  vi.stubGlobal("fetch", vi.fn(async () => response({ start: "2026-07", end: "2026-07", as_of: "2026-07-31", period_state: "month_end", complete: true,
    dimensions: { month: [], item: [], customer: [], project: [] }, excluded: [], service_costs: [], service_cost_total: "0.00", basis_label: "货物单列",
    service_margin: { rows: [service("甲", "0.00"), service("乙", null)], unplaced: [], complete: false, basis_label: "明确归类后按月份项目匹配" } })));
  const wrapper = mount(CostAnalysis, { props: { company, mode: "analysis", saved: 0 } });
  await flushPromises();
  const rows = wrapper.findAll('[aria-label="服务项目毛利"] tbody tr');
  expect(rows[0]!.text()).toContain("0.00");
  expect(rows[0]!.text()).toContain("已核实零成本");
  expect(rows[0]!.text()).toContain("0011");
  expect(rows[1]!.findAll("td").slice(3, 5).map(n => n.text())).toEqual(["待核对", "待核对"]);
  expect(rows[1]!.text()).toContain("未录入成本");
});

it("shows uniform markup evidence and alias candidates without providing automatic merge or repricing", async () => {
  const source = { date: "2026-07-03", invoice_number: "00012", source_file: "a.xml" };
  vi.stubGlobal("fetch", vi.fn(async () => response({ alerts: [{ code: "uniform_actual_markup", state: "review", message: "留存定价依据", sample_count: 3, markup_percent: "8.00" }],
    tax_suggestions: [], basis_label: "核对",
    uniform_markup: { state: "uniform", sample_count: 3, unknown_count: 0, markup_percent: "8.00", basis_label: "按原月成本，0.01个百分点",
      samples: [{ markup_percent: "8.00", revenue: "108.00", cost: "100.00", sources: [{ ...source, name: "钢筋", spec: "12E", unit: "吨" }] }] },
    alias_candidates: { truncated: false, items: [{ names: ["钢筋", "抗震钢筋"], spec: "12E", unit: "吨", reason: "规格与单位相同", sources: [{ name: "钢筋", count: 1, invoices: [source] }] }] } })));
  const wrapper = mount(CostAnalysis, { props: { company, mode: "monitor", saved: 0 } });
  await flushPromises();
  expect(wrapper.text()).toContain("实际加价率一致（1）");
  expect(wrapper.text()).toContain("3 个样本 · 8.00%");
  expect(wrapper.get('[aria-label="实际加价率样本"]').text()).toContain("108.00");
  expect(wrapper.get('[aria-label="同物异名候选"]').text()).toContain("钢筋 / 抗震钢筋");
  expect(wrapper.text()).toContain("00012");
  expect(wrapper.findAll("button").some(n => /自动合并|自动改价/.test(n.text()))).toBe(false);
});

it("clears old period results when the next query fails", async () => {
  let reject = false;
  vi.stubGlobal("fetch", vi.fn(async () => reject ? response({ detail: "读取失败" }, 409) : response({ alerts: [], tax_suggestions: [], basis_label: "旧期间数据" })));
  const wrapper = mount(CostAnalysis, { props: { company, mode: "monitor", saved: 0 } });
  await flushPromises();
  expect(wrapper.text()).toContain("旧期间数据");
  reject = true;
  await wrapper.get('[aria-label="截止月"]').setValue("2026-07");
  await button(wrapper, "查询").trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("读取失败");
  expect(wrapper.text()).not.toContain("旧期间数据");
});

it("requires the exact classification preview, queries unknown writes and invalidates a shared-source preview", async () => {
  let unknown = true;
  const calls: { method: string; body?: Record<string, unknown> }[] = [];
  const payload = { revision: "rev", items: [{ name: "施工服务", standard_name: "施工服务", type: "goods", sources: ["销项"] }] };
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET", body = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, body });
    if (method === "PUT") return unknown ? response({}, 503) : response({ changed: true });
    if (method === "POST") return response({ preview_hash: "types-hash", changes: [{ name: "施工服务", before: "goods", after: "service" }] });
    return response(payload);
  }));
  const wrapper = mount(CostItemTypes, { props: { company, saved: 0 }, global: { stubs: { teleport: true } } });
  await button(wrapper, "品目类型与服务收入…").trigger("click"); await flushPromises();
  await wrapper.get('[aria-label="类型 施工服务"]').setValue("service");
  await button(wrapper, "预览归类").trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("货物 → 服务");
  await button(wrapper, "确认保存归类").trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("结果待核对");
  expect(button(wrapper, "预览归类").attributes("disabled")).toBeDefined();
  expect(calls.filter(c => c.method === "PUT")).toHaveLength(1);
  expect(calls.find(c => c.method === "PUT")!.body).toEqual({ revision: "rev", types: { 施工服务: "service" }, preview_hash: "types-hash", confirm: true });
  unknown = false;
  await button(wrapper, "读取保存结果").trigger("click"); await flushPromises();
  expect(button(wrapper, "确认保存归类").attributes("disabled")).toBeDefined();
  expect(calls.filter(c => c.method === "PUT")).toHaveLength(1);
  // A new shared snapshot invalidates an outstanding preview while retaining a dirty draft.
  await wrapper.get('[aria-label="类型 施工服务"]').setValue("service");
  await button(wrapper, "预览归类").trigger("click"); await flushPromises();
  await wrapper.setProps({ saved: 1 }); await flushPromises();
  expect(wrapper.get('[aria-label="类型 施工服务"]').element).toHaveProperty("value", "service");
  expect(wrapper.text()).toContain("草稿保留");
  expect(button(wrapper, "确认保存归类").attributes("disabled")).toBeDefined();
});

it.each([
  { name: "service", component: CostServiceCosts, payload: { revision: 1, source_revision: "src", costs: { s1: { month: "2026-07", project: "甲", amount: "100.00", source: "合同" } } }, field: "金额 1", value: "120" },
  { name: "inventory", component: CostInventorySetup, payload: { revision: "src", config_revision: 0, binding_state: "current", accounts: [], book_error: "", setup: { mappings: {}, opening: null, covered_months: [], source: "" } }, field: "对照来源说明", value: "新来源" },
])("keeps $name drafts and rejects a late preview after another tab saves", async ({ component, payload, field, value }) => {
  let resolvePreview!: (result: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit = {}) => {
    if (init.method === "POST") return new Promise<Response>(resolve => { resolvePreview = resolve; });
    return response(payload);
  }));
  const wrapper = mount(component as Component, { props: { company, saved: 0, snapshot: null }, global: { stubs: { teleport: true } } });
  await flushPromises();
  await wrapper.get(`[aria-label="${field}"]`).setValue(value);
  await button(wrapper, "预览").trigger("click"); await flushPromises();
  await wrapper.setProps({ saved: 1 });
  resolvePreview(response({ preview_hash: "late", before: {}, after: {} })); await flushPromises();
  expect(wrapper.get(`[aria-label="${field}"]`).element).toHaveProperty("value", value);
  expect(wrapper.text()).toContain("草稿保留");
  expect(button(wrapper, "预览").attributes("disabled")).toBeDefined();
  expect(button(wrapper, "确认保存…").attributes("disabled")).toBeDefined();
  expect(wrapper.text()).not.toContain("late");
});

it("drops an in-flight classification preview after the shared snapshot changes", async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit = {}) => init.method === "POST"
    ? new Promise<Response>(resolve => { finish = resolve; })
    : response({ revision: "one", items: [{ name: "劳务", standard_name: "劳务", type: "goods", sources: ["销项"] }] })));
  const wrapper = mount(CostItemTypes, { props: { company, saved: 0 }, global: { stubs: { teleport: true } } });
  await button(wrapper, "品目类型与服务收入…").trigger("click"); await flushPromises();
  await wrapper.get('[aria-label="类型 劳务"]').setValue("service");
  await button(wrapper, "预览归类").trigger("click"); await flushPromises();
  await wrapper.setProps({ saved: 1 });
  finish(response({ preview_hash: "late", changes: [{ name: "不应出现", before: "goods", after: "service" }] })); await flushPromises();
  expect(wrapper.text()).not.toContain("不应出现");
  expect(button(wrapper, "确认保存归类").attributes("disabled")).toBeDefined();
});
