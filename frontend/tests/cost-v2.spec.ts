import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import CostItems from "../src/components/CostItems.vue";
import CostQuote from "../src/components/CostQuote.vue";
import CostRules from "../src/components/CostRules.vue";
import type { CostItem, CostSnapshot, MigrationView, QuoteRow } from "../src/api/costV2";
import type { Company } from "../src/api/types";

const KEY = "a".repeat(40);
const company = { id: "co_cost", name: "合成公司", root_path: "/合成公司", subdirs: [] } as unknown as Company;
const issued = { source: "manual_snapshot", quantity: "2", net_amount: "300.00", tax_amount: "39.00", gross_amount: "339.00" };
const item = (extra: Partial<CostItem> = {}): CostItem => ({
  key: KEY, name: "螺纹钢", spec: "12E", unit: "吨", quantity: "20", category_key: "钢材\u001f吨", account_code: "",
  closing_quantity: "12", closing_amount: "2000.00", closing_weighted_unit_cost: "166.666666", historical_average_unit_cost: "150",
  latest_purchase_unit_cost: "200", latest_purchase_date: "2026-07-02", cost_tax_basis: "不含税", output_tax_rate_percent: "13",
  legacy_markup_percent: "12", legacy_state: "active",
  v1_reference: { cost_unit_price: "150.00", net_unit_price: "168.00", gross_unit_price: "189.84", markup_percent: "12", cost_basis: "不含税", basis: "historical_average" },
  manual_issued_snapshot: issued, actual_issued: { ...issued, source: "sales_invoices", quantity: "8", invoice_count: 2 }, issued, warnings: [], ...extra,
});
const snapshot = (extra: Partial<CostSnapshot> = {}): CostSnapshot => ({
  company_id: "co_cost", pricing_date: "2026-07-31", revision: "rev1", rules_revision: 3, rules: {}, legacy_migrated: [], customers: ["甲公司"],
  default_markup_percent: "8", items: [item()], complete: true, warnings: [], basis_label: "", sources: {},
  book_reconciliation: { state: "needs_review", message: "", missing_months: [], items: [] }, ...extra,
});
const row = (extra: Partial<QuoteRow> = {}): QuoteRow => ({
  key: KEY, name: "螺纹钢", spec: "12E", unit: "吨", cost_unit_price: "166.67", quantity: "3", output_tax_rate_percent: "13",
  rule: { id: "legacy:x", source: "legacy", scope: "line", customer: "", item_key: KEY, kind: "markup", value: "12", valid_from: "", valid_to: "", price_basis: "net", tax_method: "ordinary" },
  overridden_rules: [], net_unit_price: "186.67", gross_unit_price: "210.94", net_amount: "560.01", tax_amount: "72.80", gross_amount: "632.81",
  markup_percent: "12", gross_margin_percent: "10.7", state: "priced", warnings: [], steps: ["成本 166.67 × (1 + 12%)"], ...extra,
});
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const button = (wrapper: ReturnType<typeof mount>, text: string) => wrapper.findAll("button").find(node => node.text().startsWith(text))!;
const options = (extra: Record<string, unknown> = {}) => ({ props: { company, snapshot: snapshot(), busy: false, ...extra }, global: { stubs: { teleport: true } } });
type Call = { url: string; method: string; body?: Record<string, unknown> };
function backend(handler: (call: Call) => Response | Promise<Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const call = { url, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    return handler(call);
  }));
  return calls;
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.innerHTML = ""; });

describe("pricing assistant", () => {
  it("quotes the exact inputs, totals in cents and archives only after preview + confirm", async () => {
    const calls = backend(call => {
      if (call.url.endsWith("/quote")) return response({ items: [row()] });
      if (call.url.includes("/records?")) return response({ revision: 4, count: 0, items: [] });
      if (call.url.endsWith("/records/preview")) return response({ records_revision: 4, preview_hash: "h1", content: { pricing_date: "2026-07-31", cost_revision: "rev1", rules_revision: 3 } });
      return response({ ok: true, changed: true });
    });
    const wrapper = mount(CostQuote, options());
    await wrapper.get('[aria-label="客户"]').setValue(" 甲公司 ");
    await wrapper.get('[aria-label="搜索品目"]').setValue("螺纹");
    await button(wrapper, "螺纹钢").trigger("click");
    await wrapper.get('[aria-label="数量 1"]').setValue("3");
    await button(wrapper, "试算报价").trigger("click"); await flushPromises();
    expect(calls[0]!.body).toEqual({ revision: "rev1", pricing_date: "2026-07-31", customer: "甲公司", lines: [{ key: KEY, quantity: "3" }] });
    expect(wrapper.text()).toContain("632.81");
    expect(wrapper.text()).toContain("旧行级加价率");
    await wrapper.get('[aria-label="数量 1"]').setValue("4");
    expect(button(wrapper, "归档此报价").attributes("disabled")).toBeDefined();
    await wrapper.get('[aria-label="数量 1"]').setValue("3");
    await button(wrapper, "归档此报价").trigger("click"); await flushPromises();
    expect(calls.filter(call => call.method === "PUT")).toHaveLength(0);
    await button(wrapper, "确认归档").trigger("click"); await flushPromises();
    const put = calls.find(call => call.method === "PUT")!;
    expect(put.url).toMatch(/\/records\/q-[a-z0-9]+$/);
    expect(put.body).toEqual({ kind: "quote", request: calls[0]!.body, records_revision: 4, preview_hash: "h1", confirm: true });
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("keeps an unknown total unknown and an unknown archive queryable, never re-archived", async () => {
    let puts = 0;
    let queryFails = true;
    const calls = backend(call => {
      if (call.url.endsWith("/quote")) return response({ items: [row({ net_amount: null, tax_amount: null, gross_amount: null, state: "needs_review" })] });
      if (call.url.includes("/records?")) return response({ revision: 0, count: 0, items: [] });
      if (call.url.endsWith("/records/preview")) return response({ records_revision: 0, preview_hash: "h", content: { pricing_date: "2026-07-31", cost_revision: "rev1", rules_revision: 3 } });
      if (call.method === "PUT") { puts++; return response({}, 503); }
      return queryFails ? response({}, 503) : response({ record: {} });
    });
    const wrapper = mount(CostQuote, options());
    await wrapper.get('[aria-label="搜索品目"]').setValue("12E");
    await button(wrapper, "螺纹钢").trigger("click");
    await button(wrapper, "试算报价").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("有待核对行，合计未知");
    await button(wrapper, "归档此报价").trigger("click"); await flushPromises();
    await button(wrapper, "确认归档").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("不会自动重发");
    expect(button(wrapper, "归档此报价").attributes("disabled")).toBeDefined();
    await button(wrapper, "归档此报价").trigger("click"); await flushPromises();
    await button(wrapper, "试算报价").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("查询归档结果");
    await button(wrapper, "查询归档结果").trigger("click"); await flushPromises();
    expect(button(wrapper, "归档此报价").attributes("disabled")).toBeDefined();
    queryFails = false;
    await button(wrapper, "查询归档结果").trigger("click"); await flushPromises();
    expect(puts).toBe(1);
    expect(calls.filter(call => call.url.endsWith("/records/preview"))).toHaveLength(1);
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("discards an archive preview read when the company changes while the list is pending", async () => {
    let finish!: (value: Response) => void;
    const calls = backend(call => call.url.endsWith("/quote") ? response({ items: [row()] })
      : new Promise<Response>(resolve => { finish = resolve; }));
    const wrapper = mount(CostQuote, options());
    await wrapper.get('[aria-label="搜索品目"]').setValue("12E");
    await button(wrapper, "螺纹钢").trigger("click");
    await button(wrapper, "试算报价").trigger("click"); await flushPromises();
    await button(wrapper, "归档此报价").trigger("click"); await flushPromises();
    await wrapper.setProps({ company: { ...company, id: "co_other" }, snapshot: snapshot({ company_id: "co_other" }) });
    finish(response({ revision: 0 })); await flushPromises();
    expect(calls.filter(call => call.url.endsWith("/records/preview"))).toHaveLength(0);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  });
});

const migration = (): MigrationView => ({
  pricing_date: "2026-07-31", revision: "rev1", rules_revision: 3, legacy_migrated: ["b".repeat(40)], complete: true, basis_label: "",
  summary: { same: 0, different: 1, needs_review: 0, legacy_active: 1, legacy_migrated: 0, legacy_none: 0 },
  rows: [{ key: KEY, name: "螺纹钢", spec: "12E", unit: "吨", output_tax_rate_percent: "13", legacy_markup_percent: "12", legacy_state: "active",
    v1: item().v1_reference, v2: { cost_unit_price: "166.67", historical_average_unit_cost: "150", latest_purchase_unit_cost: "200", rule: { id: "legacy:x", source: "legacy", scope: "line", kind: "markup", value: "12", price_basis: "net" }, net_unit_price: "186.67", gross_unit_price: "210.94", state: "priced", warnings: [], steps: [] },
    v2_without_legacy: { rule: { id: "fallback", source: "fallback", kind: "markup", value: "8" }, net_unit_price: "180.00", gross_unit_price: "203.40", state: "priced" },
    difference_net_unit_price: "18.67", state: "different", warnings: [] }],
});

describe("items and migration", () => {
  it("shows actual sales instead of adding them to the manual snapshot", () => {
    const wrapper = mount(CostItems, options());
    expect(wrapper.text()).toContain("8（销项实际）");
    expect(wrapper.text()).not.toContain("10（");
  });

  it("previews a line-rule migration with the unioned list and confirms with the shown hash", async () => {
    const calls = backend(call => {
      if (call.url.includes("/migration?")) return response(migration());
      if (call.url.endsWith("/rules/preview")) return response({ preview_hash: "mh", before: [row()], after: [row({ rule: { ...row().rule, id: "legacy-aaaaaaaaaaaa", source: "saved" } })], rules: {}, legacy_migrated: [], revision: "rev1", rules_revision: 3 });
      return response({ ok: true, changed: true });
    });
    const wrapper = mount(CostItems, options({ snapshot: snapshot({ legacy_migrated: ["b".repeat(40)] }) }));
    await button(wrapper, "新旧对照与迁移").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("+18.67");
    await button(wrapper, "预览迁移").trigger("click"); await flushPromises();
    const preview = calls.find(call => call.url.endsWith("/rules/preview"))!.body!;
    expect(preview.legacy_migrated).toEqual([KEY, "b".repeat(40)].sort());
    expect(preview.rules).toEqual({ "legacy-aaaaaaaaaaaa": { scope: "line", customer: "", item_key: KEY, kind: "markup", value: "12", valid_from: "", valid_to: "", price_basis: "net", tax_method: "ordinary" } });
    await button(wrapper, "确认迁移").trigger("click"); await flushPromises();
    expect(calls.find(call => call.method === "PUT")!.body).toEqual({ ...preview, preview_hash: "mh", confirm: true });
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("drops a v1 rate without creating a rule and never replays a conflicted migration", async () => {
    const calls = backend(call => {
      if (call.url.includes("/migration?")) return response(migration());
      if (call.url.endsWith("/rules/preview")) return response({ preview_hash: "mh", before: [row()], after: [row()], rules: {}, legacy_migrated: [], revision: "rev1", rules_revision: 3 });
      return response({ detail: "来源已变化", error: { code: "COST_V2_CONFLICT" } }, 409);
    });
    const wrapper = mount(CostItems, options());
    await button(wrapper, "新旧对照与迁移").trigger("click"); await flushPromises();
    await wrapper.get(`[aria-label="迁移方式 螺纹钢"]`).setValue("drop");
    await button(wrapper, "预览迁移").trigger("click"); await flushPromises();
    expect(calls.find(call => call.url.endsWith("/rules/preview"))!.body!.rules).toEqual({});
    await button(wrapper, "确认迁移").trigger("click"); await flushPromises();
    expect(calls.filter(call => call.method === "PUT")).toHaveLength(1);
    expect(wrapper.emitted("reload")).toHaveLength(1);
    expect(wrapper.text()).toContain("来源已变化");
  });

  it("exports the comparison bound to the revision on screen", async () => {
    const calls = backend(call => call.url.includes("/migration?") ? response(migration()) : new Response("xlsx", { status: 200 }));
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const wrapper = mount(CostItems, options());
    await button(wrapper, "新旧对照与迁移").trigger("click"); await flushPromises();
    await button(wrapper, "导出 V2 开票参考对照").trigger("click"); await flushPromises();
    const exported = calls.find(call => call.url.endsWith("/migration/export"))!;
    expect(exported.body).toEqual({ revision: "rev1", pricing_date: "2026-07-31" });
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("unlocks an unknown migration after a successful read of the unchanged rules revision", async () => {
    const calls = backend(call => {
      if (call.url.includes("/migration?")) return response(migration());
      if (call.method === "PUT") return response({}, 503);
      return response({ preview_hash: "mh", before: [row()], after: [row()] });
    });
    const wrapper = mount(CostItems, options());
    await button(wrapper, "新旧对照与迁移").trigger("click"); await flushPromises();
    await button(wrapper, "预览迁移").trigger("click"); await flushPromises();
    await button(wrapper, "确认迁移").trigger("click"); await flushPromises();
    expect(button(wrapper, "预览迁移").attributes("disabled")).toBeDefined();
    await wrapper.setProps({ busy: true });
    await wrapper.setProps({ busy: false });
    expect(wrapper.text()).toContain("不会自动重发");
    expect(button(wrapper, "预览迁移").attributes("disabled")).toBeDefined();
    await wrapper.setProps({ snapshot: snapshot() }); await flushPromises();
    expect(button(wrapper, "预览迁移").attributes("disabled")).toBeUndefined();
    expect(wrapper.text()).not.toContain("不会自动重发");
    expect(calls.filter(call => call.method === "PUT")).toHaveLength(1);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
  });
});

describe("pricing rules", () => {
  async function addCompanyRule(wrapper: ReturnType<typeof mount>, value = "10"): Promise<void> {
    await button(wrapper, "新增规则").trigger("click");
    await wrapper.get('[aria-label="规则值"]').setValue(value);
    await button(wrapper, "放入草稿").trigger("click");
  }

  it("previews the full draft without the migration list and saves with the shown hash", async () => {
    const calls = backend(call => call.url.endsWith("/rules/preview")
      ? response({ preview_hash: "rh", before: [row()], after: [row({ net_unit_price: "183.33" })], rules: {}, legacy_migrated: [], revision: "rev1", rules_revision: 3 })
      : response({ ok: true, changed: true }));
    const wrapper = mount(CostRules, options({ snapshot: snapshot({ legacy_migrated: [KEY] }) }));
    await addCompanyRule(wrapper);
    await button(wrapper, "试算").trigger("click"); await flushPromises();
    const body = calls[0]!.body!;
    expect(body).not.toHaveProperty("legacy_migrated");
    expect(Object.values(body.rules as object)).toEqual([{ scope: "company", customer: "", item_key: "", kind: "markup", value: "10", valid_from: "", valid_to: "", price_basis: "net", tax_method: "ordinary" }]);
    expect(wrapper.text()).toContain("受影响 1 行");
    await button(wrapper, "确认保存").trigger("click");
    await button(wrapper, "确认保存规则").trigger("click"); await flushPromises();
    expect(calls[1]).toMatchObject({ method: "PUT", body: { ...body, preview_hash: "rh", confirm: true } });
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("invalidates a preview on edit and locks after an unknown save", async () => {
    let puts = 0;
    backend(call => {
      if (call.method === "PUT") { puts++; return response({}, 503); }
      return response({ preview_hash: "rh", before: [row()], after: [row()], rules: {}, legacy_migrated: [], revision: "rev1", rules_revision: 3 });
    });
    const wrapper = mount(CostRules, options());
    await addCompanyRule(wrapper);
    await button(wrapper, "试算").trigger("click"); await flushPromises();
    await addCompanyRule(wrapper, "11");
    expect(button(wrapper, "确认保存").attributes("disabled")).toBeDefined();
    await wrapper.findAll("button").filter(node => node.text() === "删除")[0]!.trigger("click");
    await button(wrapper, "试算").trigger("click"); await flushPromises();
    await button(wrapper, "确认保存").trigger("click");
    await button(wrapper, "确认保存规则").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("不会自动重发");
    expect(button(wrapper, "试算").attributes("disabled")).toBeDefined();
    await wrapper.setProps({ snapshot: null });
    expect(button(wrapper, "试算").attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("不会自动重发");
    await wrapper.setProps({ snapshot: snapshot() });
    expect(button(wrapper, "试算").attributes("disabled")).toBeUndefined();
    expect(wrapper.text()).not.toContain("不会自动重发");
    expect(wrapper.text()).toContain("有未保存的修改");
    expect(puts).toBe(1);
  });

  it("discards a late rule preview after a new snapshot was read", async () => {
    let finish!: (value: Response) => void;
    const calls = backend(() => new Promise<Response>(resolve => { finish = resolve; }));
    const wrapper = mount(CostRules, options());
    await addCompanyRule(wrapper);
    await button(wrapper, "试算").trigger("click"); await flushPromises();
    await wrapper.setProps({ snapshot: snapshot({ revision: "rev2" }) });
    finish(response({ preview_hash: "stale", before: [row()], after: [row()] })); await flushPromises();
    expect(button(wrapper, "确认保存").attributes("disabled")).toBeDefined();
    expect(button(wrapper, "试算").attributes("disabled")).toBeUndefined();
    expect(calls).toHaveLength(1);
  });

  it("rejects an invalid tier ladder before posting", async () => {
    const calls = backend(() => response({}));
    const wrapper = mount(CostRules, options());
    await button(wrapper, "新增规则").trigger("click");
    await wrapper.get('[aria-label="规则类型"]').setValue("tiered");
    await wrapper.get('[aria-label="第 1 档数值"]').setValue("10");
    await button(wrapper, "添加一档").trigger("click");
    await wrapper.get('[aria-label="第 2 档起点"]').setValue("0");
    await wrapper.get('[aria-label="第 2 档数值"]').setValue("5");
    await button(wrapper, "放入草稿").trigger("click");
    expect(wrapper.text()).toContain("阶梯起点须严格递增");
    expect(calls).toHaveLength(0);
  });
});

describe("display helpers", () => {
  it("shortens 50-digit unit costs half-up on the string and reads object warnings", async () => {
    const { unitCost, warningText } = await import("../src/api/costV2");
    expect(unitCost("166.66666666666666666666666666666666666666666666667")).toBe("166.6667");
    expect(unitCost("1999.99995")).toBe("2,000");
    expect(unitCost("40")).toBe("40");
    expect(unitCost(null)).toBe("未知");
    expect(warningText({ code: "opening_zero", message: "期初库存按 0 起算" })).toBe("期初库存按 0 起算");
  });
});
