import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import App from "../src/App.vue";
import { money } from "../src/format";
import { createAppRouter } from "../src/router";

const SUBDIRS = [
  { key: "cost_invoice_dir", label: "成本发票", relative_path: "成本发票", path: "/合成/甲/成本发票", status: "present" },
  { key: "issued_invoice_dir", label: "开具发票", relative_path: "开具发票", path: "/合成/甲/开具发票", status: "missing" },
];
const COMPANY = {
  id: "co_1", name: "甲公司", root_dir: "/合成/甲", root_path: "/合成/甲", root_status: "present", subdirs: SUBDIRS,
  missing_subdir_count: 1, taxpayer_periods: [], current_taxpayer_type: null, current_taxpayer_label: "未设置",
  monitored: true, monitored_subdir_key: "cost_invoice_dir",
};
const OTHER = { ...COMPANY, id: "co_2", name: "乙公司", monitored: false, monitored_subdir_key: null, missing_subdir_count: 0 };
const DIRECTORIES = [
  { ...SUBDIRS[0], target_id: "t1", active: true, read_only: false, projection: { summary_exists: true, summary_updated_at: "2026-11-10 10:00:00", cost_detail_exists: true, cost_detail_updated_at: "" }, freshness: { state: "monitored", message: "" } },
  { ...SUBDIRS[1], target_id: "t2", active: false, read_only: true, projection: { summary_exists: false, summary_updated_at: "", cost_detail_exists: false, cost_detail_updated_at: "" }, freshness: { state: "missing_dir", message: "" } },
];
const TOTALS = { count: 1, pretax: "1234567.80", tax: "160493.81", total: "1395061.61" };
const LEDGER = {
  ok: true, basis_label: "票面口径：销项与进项的差额不是利润，也不是应纳税额。", granularity: "month",
  periods: [{ period: "2026-06", input: TOTALS, output: TOTALS, face_difference_pretax: "0.00", face_difference_tax: "0.00", taxpayer_types: [null] }],
  totals: { input: TOTALS, output: TOTALS, face_difference_pretax: "0.00", face_difference_tax: "0.00" },
  undated: { input: { count: 0, pretax: "0.00", tax: "0.00", total: "0.00" }, output: { count: 0, pretax: "0.00", tax: "0.00", total: "0.00" } },
  excluded: [{ direction: "input", invoice_number: "1".repeat(20), invoice_date: "2026-06-01", counterpart: "供应商", source_files: ["a.pdf"], reason: "amount_inconsistent", message: "" }],
  merged_copies: { input: 0, output: 0 }, out_of_range: { input: 0, output: 0 }, warnings: [],
  checks: [{ code: "input_total_sum", ok: false, message: "进项价税合计：各期 + 日期未识别 = 合计" }], checks_ok: false,
  sources: { input: DIRECTORIES[0], output: DIRECTORIES[1] },
};

type Handler = (url: string, init: RequestInit) => [number, unknown] | undefined;
let calls: { url: string; method: string; body: unknown }[] = [];

function stubBackend(handler: Handler = () => undefined) {
  calls = [];
  let revision = 3;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({ url, method, body: init.body ? JSON.parse(String(init.body)) : undefined });
      const custom = handler(url, init);
      const [status, body] = custom ?? defaultResponse(url, method, revision);
      if (method !== "GET" && status === 200) revision += 1;
      return new Response(JSON.stringify(body), { status });
    }),
  );
}

function defaultResponse(url: string, method: string, revision: number): [number, unknown] {
  if (url.endsWith("/health")) return [200, { ok: true, product_version: "合成", watch_dir: "/合成/甲/成本发票", target_id: "t1" }];
  if (url.endsWith("/settings")) return [200, { ok: true, watch_dir: "/合成/甲/成本发票", active_target_id: "t1" }];
  if (url === "/api/v1/companies" && method === "GET") return [200, { ok: true, revision, companies: [OTHER, COMPANY], monitored_company_id: "co_1", target_id: "t1", watch_dir: "" }];
  if (url === "/api/v1/companies" && method === "POST") return [200, { ok: true, revision: revision + 1, company: { ...OTHER, id: "co_3", name: "丙公司" }, subdir_sources: { cost_invoice_dir: "detected", issued_invoice_dir: "default" } }];
  if (url.includes("/directories?") || url.endsWith("/directories")) return [200, { ok: true, revision, company: COMPANY, directories: DIRECTORIES }];
  if (url.includes("/subdirs/plan")) return [200, { ok: true, company_id: "co_1", revision, plan_hash: "h1", create_count: 1, blocked_count: 0, items: [{ ...SUBDIRS[1], action: "create", reason: "" }] }];
  if (url.includes("/subdirs/create")) return [200, { ok: true, revision, company: COMPANY, created: ["issued_invoice_dir"], skipped: [], failed: [] }];
  if (url.includes("/ledger")) return [200, LEDGER];
  if (url.includes("/invoices")) return [200, { ok: true, count: 1, page: 1, page_size: 50, read_only: true, directory: DIRECTORIES[1], items: [] }];
  return [404, { detail: `unexpected ${method} ${url}` }];
}

async function mountCompanies() {
  setActivePinia(createPinia());
  const router = createAppRouter(createMemoryHistory());
  await router.push("/companies");
  const wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return wrapper;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("companies module", () => {
  it("lists companies, opens the monitored one and shows directory states", async () => {
    stubBackend();
    const wrapper = await mountCompanies();
    expect(wrapper.findAll(".company-item").map((item) => item.find(".company-name").text())).toEqual(["乙公司", "甲公司"]);
    expect(wrapper.get('[aria-selected="true"].company-item').text()).toContain("监控中");
    expect(wrapper.get(".detail-header h2").text()).toBe("甲公司");
    expect(wrapper.text()).toContain("补建缺失子目录（1）");
    const states = wrapper.findAll(".fresh").map((cell) => cell.text());
    expect(states).toEqual(["监控中", "目录缺失"]);
  });

  it("creates a company with the current revision and no assumed taxpayer type", async () => {
    stubBackend();
    const wrapper = await mountCompanies();
    await wrapper.get("button.block").trigger("click");
    const form = wrapper.get('form[aria-label="新建公司"]');
    const [name, root] = form.findAll("input");
    await name!.setValue("丙公司");
    await root!.setValue("/合成/丙");
    await form.trigger("submit");
    await flushPromises();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.body).toEqual({ name: "丙公司", root_dir: "/合成/丙", taxpayer_periods: [], revision: 3 });
    expect(wrapper.text()).toContain("识别到 1 个已有子目录");
  });

  it("reloads the list after a revision conflict instead of overwriting", async () => {
    stubBackend((url, init) =>
      init.method === "PATCH" ? [409, { ok: false, detail: "公司清单已被修改", error: { code: "COMPANY_REVISION_CONFLICT" } }] : undefined,
    );
    const wrapper = await mountCompanies();
    await wrapper.findAll('[role="tab"]')[2]!.trigger("click");
    const before = calls.filter((call) => call.url === "/api/v1/companies" && call.method === "GET").length;
    await wrapper.get('form[aria-label="公司设置"]').trigger("submit");
    await flushPromises();
    expect(calls.filter((call) => call.url === "/api/v1/companies" && call.method === "GET").length).toBe(before + 1);
    expect(wrapper.get('form[aria-label="公司设置"] [role="alert"]').text()).toContain("已刷新");
  });

  it("creates missing subfolders only after a preview, sending its plan hash", async () => {
    stubBackend();
    const wrapper = await mountCompanies();
    await wrapper.findAll(".toolbar button")[1]!.trigger("click");
    await flushPromises();
    const preview = wrapper.get('[aria-label="补建预览"]');
    expect(preview.text()).toContain("不移动、删除或改写");
    expect(calls.some((call) => call.url.includes("/subdirs/create"))).toBe(false);
    await preview.get("button.primary").trigger("click");
    await flushPromises();
    expect(calls.find((call) => call.url.includes("/subdirs/create"))?.body).toEqual({ plan_hash: "h1", confirm: true });
    expect(wrapper.text()).toContain("已新建 1 个");
  });

  it("asks for a new preview when the plan went stale", async () => {
    stubBackend((url) => (url.includes("/subdirs/create") ? [409, { ok: false, detail: "x", error: { code: "COMPANY_PLAN_STALE" } }] : undefined));
    const wrapper = await mountCompanies();
    await wrapper.findAll(".toolbar button")[1]!.trigger("click");
    await flushPromises();
    await wrapper.get('[aria-label="补建预览"] button.primary').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("请重新预览");
    expect(wrapper.find('[aria-label="补建预览"]').exists()).toBe(false);
  });

  it("shows failing conservation checks in red and lists excluded invoices", async () => {
    stubBackend();
    const wrapper = await mountCompanies();
    expect(calls.some((call) => call.url.includes("/ledger"))).toBe(false); // loads on first open
    await wrapper.findAll('[role="tab"]')[1]!.trigger("click");
    await flushPromises();
    expect(wrapper.get(".checks").classes()).toContain("checks--failed");
    expect(wrapper.get(".checks").attributes("open")).toBeDefined(); // a failure is never collapsed
    expect(wrapper.get(".check--failed").text()).toContain("✗");
    expect(wrapper.text()).toContain("1,234,567.80");
    expect(wrapper.text()).toContain("金额对不上");
    expect(wrapper.text()).toContain("票面口径");
  });

  it("marks a non-monitored folder's invoice list read-only", async () => {
    stubBackend((url) => (url.includes("/directories?") || url.endsWith("/directories")
      ? [200, { ok: true, revision: 3, company: COMPANY, directories: [{ ...DIRECTORIES[1], status: "present" }] }] : undefined));
    const wrapper = await mountCompanies();
    await wrapper.get(".row-actions button").trigger("click");
    await flushPromises();
    expect(wrapper.get('[aria-label="目录发票"]').text()).toContain("只读 · 上次汇总");
  });
});

describe("money", () => {
  it("groups digits on the decimal string", () => {
    expect(money("-1234567.80")).toBe("-1,234,567.80");
    expect(money("0.00")).toBe("0.00");
    expect(money("¥12")).toBe("¥12");
    expect(money("")).toBe("—");
  });
});
