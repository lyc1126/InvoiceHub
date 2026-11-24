import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import CompanyCostsV2 from "../src/components/CompanyCostsV2.vue";
import CostAnalysis from "../src/components/CostAnalysis.vue";
import CostInventorySetup from "../src/components/CostInventorySetup.vue";
import CostRecords from "../src/components/CostRecords.vue";
import CostServiceCosts from "../src/components/CostServiceCosts.vue";
import type { CostSnapshot } from "../src/api/costV2";
import type { Company } from "../src/api/types";

const KEY = "a".repeat(40);
const company = { id: "co_cost", name: "合成公司", root_path: "/合成公司", subdirs: [] } as unknown as Company;
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const button = (wrapper: ReturnType<typeof mount>, text: string) => wrapper.findAll("button").find(node => node.text().startsWith(text))!;
const stubs = { global: { stubs: { teleport: true } } };
type Call = { url: string; method: string; body?: Record<string, unknown> };
function backend(handler: (call: Call) => Response): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const call = { url, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    return handler(call);
  }));
  return calls;
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.innerHTML = ""; });

const margin = (key: string, cost: string | null) => ({ key, revenue: "1000.00", cost, gross_profit: cost === null ? null : "200.00", gross_margin_percent: cost === null ? null : "20.000000", state: cost === null ? "needs_review" : "known", sources: [{ invoice_number: "0001", source_file: "a.xml", date: "2026-07-20" }] });
const analysis = {
  start: "2026-06", end: "2026-11", as_of: "2026-11-21", period_state: "provisional", complete: false, basis_label: "合成口径",
  dimensions: { month: [margin("2026-07", null)], item: [margin("钢材\u001f吨", "800.00")], customer: [margin("甲公司", "800.00")], project: [margin("", null)] },
  excluded: [{ invoice_number: "0009", reason: "非货物收入未并入货物毛利" }], service_costs: [{ month: "2026-07", project: "一期", amount: "500.00", sources: ["分包单"] }], service_cost_total: "500.00",
};

describe("analysis and monitor", () => {
  it("shows unknown cost as 待核对, the provisional month and service costs apart from goods margin", async () => {
    const calls = backend(() => response(analysis));
    const wrapper = mount(CostAnalysis, { props: { company, mode: "analysis", saved: 0 } });
    await flushPromises();
    expect(calls[0]!.url).toContain("/analysis?start=&end=");
    expect(wrapper.text()).toContain("当前月截至 2026-11-21 暂计");
    const cells = wrapper.findAll('[aria-label="毛利分析"] tbody tr:first-child td').map(cell => cell.text());
    expect(cells.slice(1, 5)).toEqual(["1,000.00", "待核对", "待核对", "—"]);
    expect(wrapper.text()).toContain("不从货物毛利扣除");
    await button(wrapper, "按品类单位").trigger("click");
    expect(wrapper.get('[aria-label="毛利分析"]').text()).toContain("钢材 · 吨");
    await wrapper.setProps({ saved: 1 }); await flushPromises();
    expect(calls).toHaveLength(2);
  });

  it("labels monitor alerts, maps item keys to names and validates thresholds before reading", async () => {
    const calls = backend(() => response({ as_of: "2026-07-31", period_state: "month_end", basis_label: "仅核对",
      alerts: [{ code: "purchase_price_change", item_key: KEY, state: "review", message: "变动", change_percent: "33.3333", dates: ["2026-06-03", "2026-07-02"] },
        { code: "tax_rate_difference", item_key: KEY, state: "review", message: "税率不同" }],
      tax_suggestions: [{ item_key: KEY, date: "2026-07-20", tax_rate_percent: "13", source: "最近销项票面，仅供核对" }] }));
    const items = [{ key: KEY, name: "螺纹钢", spec: "12E", unit: "吨" }] as unknown as CostSnapshot["items"];
    const wrapper = mount(CostAnalysis, { props: { company, mode: "monitor", saved: 0, items } });
    await flushPromises();
    expect(calls[0]!.url).toContain("price_change_percent=30&minimum_margin_percent=0");
    expect(wrapper.text()).toContain("采购价波动（1）");
    expect(wrapper.text()).toContain("票面税率与设置不同（1）");
    expect(wrapper.text()).toContain("螺纹钢 · 12E · 吨");
    expect(wrapper.text()).toContain("33.33%");
    await wrapper.get('[aria-label="最低实际毛利"]').setValue("100");
    await button(wrapper, "查询").trigger("click"); await flushPromises();
    expect(calls).toHaveLength(1);
    expect(wrapper.text()).toContain("最低毛利小于 100");
  });
});

describe("service costs", () => {
  const payload = { revision: 1, source_revision: "src", costs: { s1: { month: "2026-07", project: "", amount: "100.00", source: "合同" } }, basis_label: "人工口径" };

  it("previews, confirms with the shown hash and never replays a conflict", async () => {
    let conflict = false;
    const calls = backend(call => {
      if (call.method === "PUT") return conflict ? response({ detail: "已变化", error: { code: "COST_V2_CONFLICT" } }, 409) : response({ ok: true, changed: true });
      if (call.url.endsWith("/preview")) return response({ preview_hash: "sh", before: payload.costs, after: call.body!.costs });
      return response(payload);
    });
    const wrapper = mount(CostServiceCosts, { props: { company, saved: 0 }, ...stubs });
    await flushPromises();
    await wrapper.get('[aria-label="金额 1"]').setValue("120.5");
    await button(wrapper, "预览").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("修改");
    await wrapper.get('[aria-label="金额 1"]').setValue("121");
    expect(button(wrapper, "确认保存").attributes("disabled")).toBeDefined();
    await button(wrapper, "预览").trigger("click"); await flushPromises();
    const preview = calls.filter(call => call.url.endsWith("/preview")).at(-1)!.body!;
    expect(preview).toEqual({ revision: 1, source_revision: "src", costs: { s1: { month: "2026-07", project: "", amount: "121", source: "合同" } } });
    await button(wrapper, "确认保存").trigger("click");
    await button(wrapper, "确认保存服务成本").trigger("click"); await flushPromises();
    expect(calls.find(call => call.method === "PUT")!.body).toEqual({ ...preview, preview_hash: "sh", confirm: true });
    expect(wrapper.emitted("changed")).toHaveLength(1);
    conflict = true;
    await wrapper.get('[aria-label="金额 1"]').setValue("130");
    await button(wrapper, "预览").trigger("click"); await flushPromises();
    await button(wrapper, "确认保存").trigger("click");
    await button(wrapper, "确认保存服务成本").trigger("click"); await flushPromises();
    expect(calls.filter(call => call.method === "PUT")).toHaveLength(2);
    expect(wrapper.text()).toContain("已变化");
  });

  it("requires month, amount and source before previewing", async () => {
    const calls = backend(() => response({ ...payload, costs: {} }));
    const wrapper = mount(CostServiceCosts, { props: { company, saved: 0 }, ...stubs });
    await flushPromises();
    await button(wrapper, "添加一行").trigger("click");
    await button(wrapper, "预览").trigger("click");
    expect(wrapper.text()).toContain("须选择月份");
    expect(calls).toHaveLength(1);
  });
});

describe("inventory setup and records", () => {
  const setup = { revision: "rev1", config_revision: 0, binding_state: "current", book_error: "", accounts: [{ code: "140501", name: "库存商品/钢材" }],
    setup: { mappings: {}, opening: null, covered_months: [], source: "" } };
  const snapshot = { items: [{ key: KEY, name: "螺纹钢" }], book_reconciliation: { state: "needs_review", message: "缺少已确认科目对照或库存期初。", missing_months: ["2026-07"],
    items: [{ key: "k", account_code: "140501", name: "钢材", unit: "吨", state: "needs_review", expected_quantity: "12", expected_amount: "2000.00", book_quantity: null, book_amount: null, quantity_difference: null, amount_difference: null }] } } as unknown as CostSnapshot;

  it("previews and confirms the exact setup shape, and shows null book differences as 待核对", async () => {
    const calls = backend(call => {
      if (call.method === "PUT") return response({ ok: true, changed: true });
      if (call.url.endsWith("/preview")) return response({ revision: "rev1", preview_hash: "ih", before: setup.setup, after: call.body!.setup });
      return response(setup);
    });
    const wrapper = mount(CostInventorySetup, { props: { company, snapshot, saved: 0 }, ...stubs });
    await flushPromises();
    expect(wrapper.get('[aria-label="账面库存核对"]').text()).toContain("待核对");
    expect(wrapper.get('[aria-label="账面库存核对"]').text()).toContain("2026-07");
    await wrapper.get('[aria-label="库存科目 螺纹钢"]').setValue("140501");
    await button(wrapper, "预览").trigger("click");
    expect(wrapper.text()).toContain("请填写对照与期初的来源说明");
    await wrapper.get('[aria-label="对照来源说明"]').setValue("2026-06 余额表");
    await wrapper.get('input[type="checkbox"]').setValue(true);
    await wrapper.get('[aria-label="期初月份"]').setValue("2026-06");
    await button(wrapper, "预览").trigger("click"); await flushPromises();
    const body = calls.find(call => call.url.endsWith("/preview"))!.body!;
    expect(body).toEqual({ revision: "rev1", setup: { mappings: { 螺纹钢: "140501" }, opening: { month: "2026-06", items: [] }, covered_months: [], source: "2026-06 余额表" } });
    await button(wrapper, "确认保存").trigger("click");
    await button(wrapper, "确认保存对照").trigger("click"); await flushPromises();
    expect(calls.find(call => call.method === "PUT")!.body).toEqual({ ...body, preview_hash: "ih", confirm: true });
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("lists records, opens the archived content and exports by its content hash", async () => {
    const record = { id: "q-1", created_at: "2026-07-31T01:02:03+00:00", content_hash: "c".repeat(64), content: { kind: "quote", pricing_date: "2026-07-31",
      request: { customer: "甲公司" }, rules_revision: 3, cost_revision: "d".repeat(64), basis_label: "口径",
      result: { items: [{ key: KEY, name: "螺纹钢", spec: "12E", unit: "吨", quantity: "3", net_unit_price: "186.67", gross_unit_price: "210.94", gross_amount: "632.81", state: "priced", warnings: [],
        rule: { source: "saved", kind: "markup", value: "12" }, market_reference: { source: "合成报价单", unit_price: "200", observed_on: "2026-07-01", valid_to: "2026-07-31" } }] } } };
    const calls = backend(call => {
      if (call.url.endsWith("/export")) return new Response("xlsx");
      if (call.url.includes("/records/q-1")) return response({ record });
      return response({ revision: 1, count: 1, items: [{ id: "q-1", created_at: record.created_at, content_hash: record.content_hash, kind: "quote", pricing_date: "2026-07-31", customer: "甲公司" }] });
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const wrapper = mount(CostRecords, { props: { company, saved: 0 } });
    await flushPromises();
    await button(wrapper, "q-1").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("632.81");
    expect(wrapper.text()).toContain("合成报价单");
    await button(wrapper, "导出 XLSX").trigger("click"); await flushPromises();
    expect(calls.find(call => call.url.endsWith("/q-1/export"))!.body).toEqual({ confirm: true, content_hash: record.content_hash });
  });
});

describe("company cost workbench", () => {
  it("drops the previous date's prices when a new planning date is rejected", async () => {
    const good = { company_id: "co_cost", pricing_date: "2026-07-31", revision: "r", rules_revision: 0, rules: {}, legacy_migrated: [], customers: [], default_markup_percent: "8",
      items: [{ key: KEY, name: "合成七月品目", spec: "", unit: "吨" }], complete: true, warnings: [{ code: "x", message: "对象警告" }], basis_label: "", sources: {},
      book_reconciliation: { state: "needs_review", message: "", missing_months: [], items: [] } };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.includes("2026-05-31")
      ? response({ detail: "所选日期早于已确认库存期初。" }, 422) : response(good)));
    const wrapper = mount(CompanyCostsV2, { props: { company }, ...stubs });
    const date = wrapper.get('[aria-label="计划开票日"]');
    await date.setValue("2026-07-31"); await date.trigger("change"); await flushPromises();
    expect(wrapper.text()).toContain("对象警告");
    await wrapper.get('[aria-label="搜索品目"]').setValue("七月");
    expect(wrapper.text()).toContain("合成七月品目");
    await date.setValue("2026-05-31"); await date.trigger("change"); await flushPromises();
    expect(wrapper.text()).toContain("早于已确认库存期初");
    expect(wrapper.text()).not.toContain("合成七月品目");
    expect(wrapper.text()).not.toContain("对象警告");
  });

  it("reads the company snapshot for the chosen pricing date and drops a late reply from another company", async () => {
    let finish!: (value: Response) => void;
    const late = new Promise<Response>(resolve => { finish = resolve; });
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      if (urls.length === 1) return late;
      return response({ company_id: "co_other", pricing_date: "2026-07-31", revision: "r", rules_revision: 0, rules: {}, legacy_migrated: [], customers: [], default_markup_percent: "8",
        items: [], complete: false, warnings: ["合成提示"], basis_label: "", sources: {}, book_reconciliation: { state: "needs_review", message: "", missing_months: [], items: [] } });
    }));
    const wrapper = mount(CompanyCostsV2, { props: { company }, ...stubs });
    await wrapper.setProps({ company: { ...company, id: "co_other" } }); await flushPromises();
    finish(response({ company_id: "co_cost", warnings: ["迟到旧公司"], items: [], complete: true, sources: {} })); await flushPromises();
    expect(urls[1]).toMatch(/^\/api\/v1\/companies\/co_other\/cost-analysis\/v2\?pricing_date=\d{4}-\d{2}-\d{2}$/);
    expect(wrapper.text()).not.toContain("迟到旧公司");
    expect(wrapper.text()).toContain("合成提示");
    expect(wrapper.text()).toContain("来源投影不完整");
    await wrapper.get('[aria-label="计划开票日"]').setValue("2026-07-31");
    await wrapper.get('[aria-label="计划开票日"]').trigger("change"); await flushPromises();
    expect(urls.at(-1)).toContain("pricing_date=2026-07-31");
  });
});
