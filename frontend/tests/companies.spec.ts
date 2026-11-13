import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import App from "../src/App.vue";
import { money } from "../src/format";
import { createAppRouter } from "../src/router";
import PeriodFolderCheck from "../src/components/PeriodFolderCheck.vue";
import type { Company } from "../src/api/types";

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
  if (url === "/api/v1/invoice-tags" && method === "GET") return [200, { ok: true, revision: 1, tags: [] }];
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
  localStorage.clear();
});

describe("companies module", () => {
  it("lists companies, opens the monitored one and shows directory states", async () => {
    stubBackend();
    const wrapper = await mountCompanies();
    expect(wrapper.findAll(".ws-row--company .ws-label").map((item) => item.text())).toEqual(["乙公司", "甲公司"]);
    // The monitored company opens as the first tab; the sidebar footer names the one watched folder.
    expect(wrapper.get('.ws-tab [aria-selected="true"]').text()).toContain("甲公司");
    expect(wrapper.get(".ws-status").text()).toContain("甲公司 · 成本发票");
    expect(wrapper.get(".detail-header h2").text()).toContain("甲公司");
    expect(wrapper.text()).toContain("补建缺失子目录（1）");
    const states = wrapper.findAll(".fresh").map((cell) => cell.text());
    expect(states).toEqual(["监控中", "目录缺失"]);
  });

  it("creates a company with the current revision and no assumed taxpayer type", async () => {
    let created = false;
    stubBackend((url, init) => {
      if (url === "/api/v1/companies" && init.method === "POST") created = true;
      return url === "/api/v1/companies" && (init.method ?? "GET") === "GET" && created
        ? [200, { ok: true, revision: 4, companies: [OTHER, COMPANY, { ...OTHER, id: "co_3", name: "丙公司" }], monitored_company_id: "co_1", target_id: "t1", watch_dir: "" }]
        : undefined;
    });
    const wrapper = await mountCompanies();
    await wrapper.get("button.ws-add").trigger("click");
    const form = wrapper.get('form[aria-label="新建公司"]');
    const [name, root] = form.findAll("input");
    await name!.setValue("丙公司");
    await root!.setValue("/合成/丙");
    await form.trigger("submit");
    await flushPromises();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.body).toEqual({ name: "丙公司", root_dir: "/合成/丙", taxpayer_periods: [], revision: 3 });
    expect(wrapper.text()).toContain("识别到 1 个已有子目录");
    // The form tab closes and the new company opens in its place.
    expect(wrapper.findAll(".ws-tab__title").map((item) => item.text())).toEqual(["甲公司", "丙公司"]);
  });

  it("reloads the list after a revision conflict instead of overwriting", async () => {
    stubBackend((url, init) =>
      init.method === "PATCH" ? [409, { ok: false, detail: "公司清单已被修改", error: { code: "COMPANY_REVISION_CONFLICT" } }] : undefined,
    );
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-settings").trigger("click");
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
    await wrapper.get("#company-tab-ledger").trigger("click");
    await flushPromises();
    expect(wrapper.get(".checks").classes()).toContain("checks--failed");
    expect(wrapper.get(".checks").attributes("open")).toBeDefined(); // a failure is never collapsed
    expect(wrapper.get(".check--failed").text()).toContain("✗");
    expect(wrapper.text()).toContain("1,234,567.80");
    expect(wrapper.text()).toContain("金额对不上");
    expect(wrapper.text()).toContain("票面口径");
  });

  it("shows a bank month without a statement as missing, never as zero", async () => {
    const bucket = { opening: "10000.00", inflow: "500.00", outflow: "100.00", closing: "10400.00", rows: 2, missing_months: [], ok: true };
    const missing = { opening: null, inflow: "0.00", outflow: "0.00", closing: null, rows: 0, missing_months: ["2026-08"], ok: false };
    const bank = {
      path: "/合成/甲/银行流水", status: "present", state: "ok", message: "", file_count: 2, cached: false,
      basis_label: "银行口径：对账单收支与余额；收付款不等于收入或成本。",
      accounts: [{
        account_no: "600011112222", account_tail: "2222", account_name: "甲公司", bank_name: "中国银行测试支行",
        label: "中国银行测试支行 尾号2222", first_month: "2026-07", last_month: "2026-09", statement_files: ["7月.pdf", "9月.pdf"],
        periods: [{ period: "2026-07", ...bucket }, { period: "2026-08", ...missing }],
        totals: { ...bucket, missing_months: ["2026-08"], ok: false },
      }],
      periods: [], totals: { inflow: "500.00", outflow: "100.00", rows: 2 },
      sources: { statements: 2, receipts: 3, unrecognized: [] },
      issues: [{ level: "错误", code: "PERIOD_GAP", message: "缺少 2026-08-01 ~ 2026-08-31 的对账单" }],
      checks: [{ code: "bank_balance:600011112222:2026-08", ok: false, message: "缺 2026-08 的对账单" }], checks_ok: false,
    };
    stubBackend((url) => (url.includes("/ledger") ? [200, { ...LEDGER, checks_ok: true, checks: [], bank }] : undefined));
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-ledger").trigger("click");
    await flushPromises();
    const section = wrapper.get('[aria-label="银行流水"]');
    expect(section.get(".checks").classes()).toContain("checks--failed");
    const august = section.findAll("tbody tr")[1]!;
    expect(august.classes()).toContain("row--failed");
    expect(august.text()).toContain("缺 2026-08 对账单");
    expect(august.findAll("td")[0]!.text()).toBe("—"); // no opening balance is made up
    expect(section.text()).toContain("10,400.00");
    expect(section.text()).toContain("回单 3 份（回单不参与汇总）");
  });

  it("explains a missing bank folder instead of showing an empty table", async () => {
    const bank = { path: "/合成/甲/银行流水", status: "missing", state: "missing_dir", message: "目录不存在或不可用。" };
    stubBackend((url) => (url.includes("/ledger") ? [200, { ...LEDGER, bank }] : undefined));
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-ledger").trigger("click");
    await flushPromises();
    const section = wrapper.get('[aria-label="银行流水"]');
    expect(section.text()).toContain("目录不存在或不可用。");
    expect(section.findAll("table")).toHaveLength(0);
  });

  it("checks the deduction lists against the cost invoices and flags what is missing", async () => {
    const row = { invoice_code: "", status: "已勾选", invoice_date: "2026-06-10 10:00:00", seller: "丙丁建材", file: "用途确认信息.xlsx", 金额: "1000.00", 有效抵扣税额: "130.00" };
    const compare = {
      ok: true, relation: "deduction", state: "ok", message: "", basis_label: "抵扣口径：已勾选不等于已申报，以申报表为准。",
      periods: [{ period: "2026-06", list_rows: 3, matched_current: 1, matched_carried: 0, matched_other: 0, list_only: 1, not_selected: 1, deductible_tax: "195.00" }],
      lists: [], duplicates: [], unrecognized: [], warnings: [],
      matched: [{ ...row, invoice_number: "1".repeat(20), period: "2026-06", 税额: "130.00", timing: "current", invoice_month: "2026-06", invoice_tax: "131.00", tax_ok: false, source_files: ["a.xml"] }],
      list_only: [{ ...row, invoice_number: "2".repeat(20), period: "2026-06", 税额: "65.00" }],
      not_selected: [],
      not_listed: { special: [{ invoice_number: "3".repeat(20), invoice_date: "2026-07-01", seller: "丙丁建材", invoice_type: "增值税专用发票", tax: "52.00", later_list_periods: [], source_files: [] }], ordinary: 2, unknown_type: [] },
      checks: [{ code: "tax_matches", ok: false, message: "1 张已勾选发票的税额与目录中的发票不一致" }], checks_ok: false,
    };
    stubBackend((url) => (url.includes("/compare") ? [200, compare] : undefined));
    const wrapper = await mountCompanies();
    expect(calls.some((call) => call.url.includes("/compare"))).toBe(false); // loads on first open
    await wrapper.get("#company-tab-compare").trigger("click");
    await flushPromises();
    const url = calls.find((call) => call.url.includes("/compare"))!.url;
    expect(url).toContain("a=cost_invoice_dir");
    expect(url).toContain("b=input_deduction_dir");
    const panel = wrapper.get('[aria-label="勾稽"]');
    expect(panel.get(".checks").classes()).toContain("checks--failed");
    expect(panel.get('[aria-label="已勾选并对上的发票"] tbody tr').classes()).toContain("row--failed");
    expect(panel.get('[aria-label="清单有、目录无"]').text()).toContain("2".repeat(20));
    expect(panel.get('[aria-label="目录有、清单无"]').text()).toContain("还没有清单");
    expect(panel.text()).toContain("普票 2 张不能抵扣");
  });

  it("switches to the stock check, marks oversold categories and drops specs down under them", async () => {
    const month = { month: "2026-06", open_qty: "2", open_amount: "8000.00", in_qty: "5", in_amount: "20000.00", out_qty: "8", cost: "28000.00", end_qty: "-1", end_amount: "0.00", unit_price: "4000.00", note: "库存不足" };
    const spec = (name: string, specText: string, inQty: string, outQty: string, net: string) =>
      ({ key: `螺纹钢\u001f${specText}\u001f吨`, name, spec: specText, unit: "吨", in_qty: inQty, in_amount: "10000.00", out_qty: outQty, net_qty: net });
    const inventory = {
      ok: true, relation: "inventory", state: "ok", message: "", basis_label: "进销存口径：按品类，月末一次加权平均。",
      first_month: "2026-06", cost_label: "不含税", excluded: [], totals: { open_amount: "8000.00", in_amount: "20000.00", cost: "28000.00", end_amount: "0.00" },
      opening: { source: "ledger", month: "2026-06", read_months: ["2026-04", "2026-05"], files: ["序时账_2026-04.txt", "序时账_2026-05.txt"], error: "",
        items: [{ code: "140501", account: "库存商品_螺纹钢", family: "螺纹钢", unit: "吨", qty: "2", amount: "8000.00" }],
        unassigned: [{ code: "140509", account: "库存商品_其他", family: "其他", unit: "", qty: "1", amount: "10.00", reason: "账套分录没有单位" }] },
      items: [{ key: "螺纹钢\u001f吨", name: "螺纹钢", unit: "吨", account_code: "140501", ...month, oversold: true, sold_never_bought: false, months: [month],
        specs: [spec("螺纹钢", "HRB40018", "2.5", "3", "-0.5"), spec("螺纹钢", "HRB400E20", "2.5", "5", "-2.5")] }],
      warnings: [{ code: "opening_ledger", message: "期初取账套读回 2026-04～2026-05" }, { code: "oversold", message: "1 个品类月份卖超" }],
      checks: [{ code: "spec_breakdown", ok: true, message: "规格之和 = 品类合计" }], checks_ok: true,
    };
    stubBackend((url) => (url.includes("b=issued_invoice_dir") ? [200, inventory] : undefined));
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-compare").trigger("click");
    await flushPromises();
    await wrapper.get('select[aria-label="比较关系"]').setValue("inventory");
    await flushPromises();
    expect(calls.some((call) => call.url.includes("b=issued_invoice_dir"))).toBe(true); // reloads on switch
    const table = wrapper.get('table[aria-label="进销存"]');
    expect(table.get("tbody tr").classes()).toContain("row--failed");
    expect(table.text()).toContain("卖超");
    expect(table.text()).toContain("140501");
    expect(wrapper.text()).toContain("期初取账套读回 2026-04～2026-05");
    expect(wrapper.get('[aria-label="未计入期初的账套明细"]').text()).toContain("账套分录没有单位");
    // Specs stay closed until asked for, then open as rows without an opening or a cost of their own.
    expect(table.findAll("tr.row--spec")).toHaveLength(0);
    const toggle = table.get('button[aria-label="螺纹钢 的 2 个规格"]');
    await toggle.trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    const specRows = table.findAll("tr.row--spec");
    expect(specRows).toHaveLength(2);
    expect(specRows[0]!.text()).toContain("HRB40018");
    expect(specRows[1]!.text()).toContain("净 -2.5");
    expect(specRows[1]!.text()).not.toContain("28,000");
  });

  it("opens a category's calculation and narrows the side-by-side source records to it", async () => {
    const month = { month: "2026-06", open_qty: "0", open_amount: "0.00", in_qty: "15", in_amount: "61000.00", out_qty: "12", cost: "48800.00", end_qty: "3", end_amount: "12200.00", unit_price: "4066.67", note: "",
      steps: ["加权单价 =（0.00 + 61000.00）÷（0 + 15）= 4066.67", "销售成本 = 12 × 61000.00 ÷ 15 = 48800.00（按未舍入单价计算）"] };
    const record = (id: string, number: string) => ({ id, invoice_number: number, invoice_date: "2026-06-03", counterpart: "丙丁建材", amount: "40000.00", source_file: `${number}.xml` });
    const inventory = {
      ok: true, relation: "inventory", state: "ok", message: "", basis_label: "进销存口径", first_month: "2026-06", cost_label: "不含税", excluded: [],
      totals: { open_amount: "0.00", in_amount: "61000.00", cost: "48800.00", end_amount: "12200.00" },
      opening: { source: "zero", month: "2026-06", read_months: [], files: [], items: [], unassigned: [], error: "" },
      items: [
        { key: "螺纹钢\u001f吨", name: "螺纹钢", unit: "吨", account_code: "", ...month, oversold: false, sold_never_bought: false, months: [month], specs: [], record_ids: { a: ["input:1", "input:2"], b: ["output:9"] } },
        { key: "盘螺\u001f吨", name: "盘螺", unit: "吨", account_code: "", ...month, oversold: false, sold_never_bought: false, months: [month], specs: [], record_ids: { a: ["input:3"], b: [] } },
      ],
      records: { a: [record("input:1", "11"), record("input:2", "22"), record("input:3", "33")], b: [record("output:9", "99")] },
      warnings: [], checks: [], checks_ok: true,
    };
    stubBackend((url) => (url.includes("b=issued_invoice_dir") ? [200, inventory] : undefined));
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-compare").trigger("click");
    await flushPromises();
    await wrapper.get('select[aria-label="比较关系"]').setValue("inventory");
    await flushPromises();
    const sources = () => wrapper.get('[aria-label="原始记录并排"]');
    expect(sources().get('table[aria-label="成本发票 原始记录"]').findAll("tbody tr")).toHaveLength(3);
    await wrapper.findAll('table[aria-label="进销存"] th button.link').find((item) => item.text() === "螺纹钢")!.trigger("click");
    const drawer = wrapper.get('[role="dialog"][aria-label="螺纹钢（吨） 明细"]');
    expect(drawer.text()).toContain("销售成本 = 12 × 61000.00 ÷ 15 = 48800.00");
    expect(document.activeElement?.getAttribute("aria-label")).toBe("关闭明细");
    expect(sources().get('table[aria-label="成本发票 原始记录"]').findAll("tbody tr").map((row) => row.text())).toEqual([
      expect.stringContaining("11"), expect.stringContaining("22"),
    ]);
    expect(sources().get('table[aria-label="开具发票 原始记录"]').text()).toContain("99");
    await sources().get("button.link").trigger("click"); // 显示全部
    expect(sources().get('table[aria-label="成本发票 原始记录"]').findAll("tbody tr")).toHaveLength(3);
    await drawer.trigger("keydown", { key: "Escape" });
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
  });

  it("opens a monitored record's original invoice through the preview pipeline and rebuilds an expired job", async () => {
    const preview = { target_id: "t1", items: [{ invoice_key: "3", source_path: "/合成/甲/成本发票/a.pdf" }] };
    const record = (id: string, number: string, extra = {}) => ({ id, invoice_number: number, invoice_date: "2026-06-03", counterpart: "丙丁建材", amount: "1.00", source_file: `${number}.pdf`, ...extra });
    const inventory = {
      ok: true, relation: "inventory", state: "ok", message: "", basis_label: "", first_month: "2026-06", cost_label: "", excluded: [],
      totals: { open_amount: "0.00", in_amount: "0.00", cost: "0.00", end_amount: "0.00" },
      opening: { source: "zero", month: "2026-06", read_months: [], files: [], items: [], unassigned: [], error: "" },
      items: [], records: { a: [record("input:1", "11", { preview })], b: [record("output:9", "99")] }, warnings: [], checks: [], checks_ok: true,
    };
    const job = (id: string) => ({ ok: true, job_id: id, keep_alive_url: `/api/v1/invoices/preview-jobs/${id}/keep-alive`, idle_timeout_seconds: 900,
      files: [{ file_number: 1, name: "a.pdf", preview_type: "pages", page_count: 2, reason: "", page_url_template: `/api/v1/invoices/preview-jobs/${id}/files/1/pages/{page_number}`, text_url: "" }] });
    let jobs = 0;
    stubBackend((url) => {
      if (url.includes("b=issued_invoice_dir")) return [200, inventory];
      if (url === "/api/v1/invoices/preview-jobs") return [200, job(`j${++jobs}`)];
      if (url.endsWith("/keep-alive")) return [410, { detail: "预览已过期" }];
      return undefined;
    });
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-compare").trigger("click");
    await flushPromises();
    await wrapper.get('select[aria-label="比较关系"]').setValue("inventory");
    await flushPromises();
    const sources = wrapper.get('[aria-label="原始记录并排"]');
    expect(sources.get('table[aria-label="开具发票 原始记录"]').text()).not.toContain("原票"); // not marked: never previewed
    await sources.get('button[aria-label="原票 11"]').trigger("click");
    await flushPromises();
    expect(calls.find((call) => call.url === "/api/v1/invoices/preview-jobs")!.body).toEqual(preview);
    const panel = () => wrapper.get('[role="dialog"][aria-label="11 原票"]');
    const page = () => panel().get("img.source-preview__page").attributes("src");
    expect(page()).toBe("/api/v1/invoices/preview-jobs/j1/files/1/pages/1");
    expect(panel().findAll('[aria-label="缩略图"] button')).toHaveLength(2);
    await panel().get('[aria-label="缩略图"] button[aria-label="第 2 页"]').trigger("click");
    expect(page()).toBe("/api/v1/invoices/preview-jobs/j1/files/1/pages/2");
    // The job expired: keep-alive gets 410, a new job is made and the same page stays open.
    vi.advanceTimersByTime(120_000);
    await flushPromises();
    expect(calls.filter((call) => call.url === "/api/v1/invoices/preview-jobs")).toHaveLength(2);
    expect(page()).toBe("/api/v1/invoices/preview-jobs/j2/files/1/pages/2");
    await panel().trigger("keydown", { key: "Escape" });
    expect(wrapper.find('[role="dialog"][aria-label="11 原票"]').exists()).toBe(false);
    const keepAlives = calls.filter((call) => call.url.endsWith("/keep-alive")).length;
    vi.advanceTimersByTime(600_000);
    await flushPromises();
    expect(calls.filter((call) => call.url.endsWith("/keep-alive")).length).toBe(keepAlives); // closed: no more keep-alive
    vi.useRealTimers();
  });

  it("shows settlement balances and keeps unallocated payments apart from invoices", async () => {
    const flow = { row_id: "S1-001", date: "2026-06-05", month: "2026-06", counterparty: "丙丁建材有限公司", details: "材料款", amount: "11300.00", file: "s.pdf", name_match: "exact" };
    const settlement = {
      ok: true, relation: "settlement", side: "payable", side_label: "应付", state: "ok", message: "",
      basis_label: "往来口径（应付）：对不上的不猜。",
      parties: [{ name: "丙丁建材有限公司", opening: "0.00", invoiced: "12430.00", settled: "12300.00", closing: "130.00", invoice_count: 2, flow_count: 2,
        unpaid: [{ invoice_number: "2".repeat(20), invoice_date: "2026-06-20", total: "1130.00", source_files: [] }],
        unallocated: [{ ...flow, row_id: "S1-002", date: "2026-07-05", amount: "1000.00", details: "部分货款" }] }],
      matches: [{ kind: "one_to_one", basis: "金额一致", flow, invoices: [{ invoice_number: "1".repeat(20), invoice_date: "2026-06-03", total: "11300.00", source_files: [] }] }],
      red_offsets: [], red_unmatched: [], ambiguous_flows: [], excluded_invoices: [],
      non_invoice_flows: [{ ...flow, row_id: "S1-003", counterparty: "张小三", amount: "2000.00", reason: "no_party" }],
      totals: { opening: "0.00", invoiced: "12430.00", settled: "12300.00", closing: "130.00" },
      warnings: [], checks: [{ code: "flow_accounting", ok: true, message: "本期流水平衡" }], checks_ok: true,
    };
    stubBackend((url) => (url.includes("b=bank_flow_dir") ? [200, settlement] : undefined));
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-compare").trigger("click");
    await flushPromises();
    await wrapper.get('select[aria-label="比较关系"]').setValue("payable");
    await flushPromises();
    expect(calls.some((call) => call.url.includes("a=cost_invoice_dir&b=bank_flow_dir"))).toBe(true);
    const parties = wrapper.get('table[aria-label="往来单位"]');
    expect(parties.text()).toContain("本期付款");
    expect(parties.text()).toContain("130.00");
    await parties.findAll("button.link").find((item) => item.text() === "明细")!.trigger("click");
    expect(parties.get('[aria-label="丙丁建材有限公司 未逐笔对应流水"]').text()).toContain("部分货款");
    expect(wrapper.get('[aria-label="逐笔对应"]').text()).toContain("1".repeat(20));
    expect(wrapper.get('[aria-label="非发票流水"]').text()).toContain("不是发票上的往来单位");
  });

  it("assigns projects to unassigned invoices and sends only the changes with the revision", async () => {
    const totals = { count: 1, pretax: "1000.00", tax: "130.00", total: "1130.00" };
    const empty = { count: 0, pretax: "0.00", tax: "0.00", total: "0.00" };
    const invoice = (number: string, source: string, project = "") => ({
      direction: "input", invoice_number: number, invoice_date: "2026-06-03", counterpart: "丙丁建材", total: "1130.00",
      project, source, remark_projects: [], assignable: true, source_files: [`${number}.xml`],
    });
    const summary = {
      ok: true, basis_label: "票面口径：差额不是项目利润。", assignments_revision: 4,
      projects: [
        { project: "甲项目", unassigned: false, input: totals, output: empty, face_difference_pretax: "-1000.00", periods: [] },
        { project: "", unassigned: true, input: totals, output: empty, face_difference_pretax: "-1000.00", periods: [] },
      ],
      project_names: ["甲项目"], unassigned_invoices: [invoice("1".repeat(20), "none")], manual_invoices: [invoice("2".repeat(20), "manual", "甲项目")],
      warnings: [], checks: [{ code: "input_total_ledger", ok: true, message: "一致" }], checks_ok: true,
    };
    stubBackend((url, init) => {
      if (url.includes("/projects/assignments")) return [200, { ok: true, assignments_revision: 5, count: 2 }];
      if (url.includes("/projects")) return [200, summary];
      return undefined;
    });
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-projects").trigger("click");
    await flushPromises();
    const table = wrapper.get('table[aria-label="项目汇总"]');
    expect(table.text()).toContain("未归属");
    expect(table.findAll("tbody tr")[1]!.classes()).toContain("row--muted");
    const form = wrapper.get('form[aria-label="项目归属"]');
    expect(form.get("button.primary").attributes("disabled")).toBeDefined(); // nothing changed yet
    await form.get(`input[aria-label="${"1".repeat(20)} 项目"]`).setValue("甲项目");
    await form.trigger("submit");
    await flushPromises();
    const put = calls.find((call) => call.method === "PUT")!;
    expect(put.body).toEqual({ revision: 4, assignments: { ["1".repeat(20)]: "甲项目" } });
    expect(wrapper.text()).toContain("已保存 1 张发票");
  });

  it("tags an invoice from the row menu, updates the dots in place and filters by tag", async () => {
    const tags = [{ id: "tag_aaaaaaaa", name: "待核实", color: "#e5484d", meaning: "金额待确认" }];
    const row = { invoice_key: "0", source_file: "a.xml", file_format: "XML", invoice_number: "1".repeat(20), seller: "丙丁", buyer: "甲", amount: "1130.00", tags: [] };
    const directory = { ...DIRECTORIES[0]!, projection: { ...DIRECTORIES[0]!.projection, summary_exists: true } };
    stubBackend((url, init) => {
      if (url === "/api/v1/invoice-tags") return [200, { ok: true, revision: 3, tags }];
      if (url.endsWith("/invoice-tags") && (init.method ?? "GET") === "GET") return [200, { ok: true, revision: 7, invoices: {} }];
      if (url.endsWith("/invoice-tags")) return [200, { ok: true, revision: 8, invoices: { ["1".repeat(20)]: ["tag_aaaaaaaa"] } }];
      if (url.includes("/invoices")) return [200, { ok: true, count: 1, page: 1, page_size: 50, read_only: false, directory, items: [row] }];
      return undefined;
    });
    const wrapper = await mountCompanies();
    const open = wrapper.findAll("button").find((button) => button.text() === "查看发票")!;
    await open.trigger("click");
    await flushPromises();
    const tr = wrapper.get('[aria-label="目录发票"] tbody tr');
    await tr.trigger("keydown", { key: "F10", shiftKey: true });
    const menu = wrapper.get('[role="menu"]');
    await menu.get('input[type="checkbox"]').setValue(true);
    await flushPromises();
    const put = calls.find((call) => call.method === "PUT")!;
    expect(put.body).toEqual({ revision: 7, changes: { ["1".repeat(20)]: ["tag_aaaaaaaa"] } });
    const dot = wrapper.get('[aria-label="目录发票"] tbody tr .tag-dot');
    expect(dot.attributes("title")).toBe("待核实：金额待确认");
    expect(calls.filter((call) => call.url.includes("/invoices?")).length).toBe(1); // no reload, no flicker
    await wrapper.get('select[aria-label="按标签筛选"]').setValue("tag_aaaaaaaa");
    await flushPromises();
    expect(calls.some((call) => call.url.includes("&tag=tag_aaaaaaaa"))).toBe(true);
  });

  it("selects invoices on the monitored folder and uses the backend for totals, printing and deletion", async () => {
    const rows = [1, 2].map((n) => ({ invoice_key: String(n), source_path: `/合成/甲/成本发票/${n}.pdf`, source_file: `${n}.pdf`, file_format: "PDF",
      invoice_number: String(n).repeat(20), seller: "丙丁", buyer: "甲", amount: "1130.00", tags: [] }));
    const directory = { ...DIRECTORIES[0]!, projection: { ...DIRECTORIES[0]!.projection, summary_exists: true } };
    const metric = (value: number) => ({ value, valid_invoice_count: 2, conflict_invoice_count: 0, missing_invoice_count: 0 });
    let confirmFails = true;
    stubBackend((url, init) => {
      const method = init.method ?? "GET";
      if (url.includes("/invoices?")) return [200, { ok: true, count: 3, page: 1, page_size: 50, read_only: false, directory, items: rows, snapshot: { provisional: false } }];
      if (url.endsWith("/selection-summary")) return [200, { ok: true, selection: { record_count: 2, invoice_count: 2, collapsed_record_count: 0 },
        totals: { pretax_amount: metric(2000), tax_amount: metric(260), total_with_tax: metric(2260) }, cost_breakdown: {} }];
      if (url.endsWith("/print-jobs")) return [200, { ok: true, print_url: "/invoices/print/j1", invoice_count: 2, page_count: 2 }];
      const job = { ok: true, job_id: "t1", trashed_count: 0, state: "prepared", files: [{ name: "1.pdf", status: "pending" }, { name: "2.pdf", status: "pending" }] };
      if (url.endsWith("/trash-jobs") && method === "POST") return [200, job];
      if (url.endsWith("/trash-jobs/t1/confirm")) return confirmFails ? [503, { detail: "连接中断" }] : [200, job];
      if (url.endsWith("/trash-jobs/t1")) return [200, { ...job, state: "completed", trashed_count: 2, files: job.files.map((file) => ({ ...file, status: "trashed" })) }];
      return undefined;
    });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const wrapper = await mountCompanies();
    await wrapper.findAll("button").find((button) => button.text() === "查看发票")!.trigger("click");
    await flushPromises();
    const list = wrapper.get('[aria-label="目录发票"]');
    await list.get('input[aria-label="勾选本页"]').setValue(true);
    vi.advanceTimersByTime(300);
    await flushPromises();
    const summaryCall = calls.find((call) => call.url.endsWith("/selection-summary"))!;
    expect(summaryCall.body).toEqual({ items: rows.map((row) => ({ invoice_key: row.invoice_key, source_path: row.source_path })) });
    const bar = wrapper.get('[aria-label="已勾选发票"]');
    expect(bar.text()).toContain("已勾选 2 张");
    expect(bar.text()).toContain("2,260.00");
    expect(bar.text()).toContain("全选筛选结果（3）");

    const popup = { location: { replace: vi.fn() }, close: vi.fn() };
    vi.stubGlobal("open", vi.fn(() => popup));
    await bar.findAll("button").find((button) => button.text() === "打印")!.trigger("click");
    await flushPromises();
    expect(popup.location.replace).toHaveBeenCalledWith("/invoices/print/j1");

    await bar.findAll("button").find((button) => button.text() === "删除所选…")!.trigger("click");
    await flushPromises();
    const trash = wrapper.get('[role="alertdialog"][aria-label="删除所选文件"]');
    expect(trash.text()).toContain("共 2 个源文件 · 待确认");
    expect(calls.some((call) => call.url.endsWith("/confirm"))).toBe(false); // nothing moves before the explicit confirm
    expect(calls.find((call) => call.url.endsWith("/trash-jobs"))!.body).toEqual({ target_id: "t1", items: (summaryCall.body as { items: unknown[] }).items });
    await trash.findAll("button").find((button) => button.text() === "确认移入废纸篓")!.trigger("click");
    await flushPromises();
    // The confirm response was lost: the page reads the journal and never confirms twice.
    expect(calls.filter((call) => call.url.endsWith("/confirm"))).toHaveLength(1);
    expect(calls.some((call) => call.url.endsWith("/trash-jobs/t1") && call.method === "GET")).toBe(true);
    expect(wrapper.find('[aria-label="已勾选发票"]').exists()).toBe(false); // completed: selection cleared, list reloaded
    expect(wrapper.get('[aria-label="删除结果"]').text()).toContain("已移入废纸篓 2 / 2 个源文件");
    vi.useRealTimers();
  });

  it("tags every selected invoice from a selected row's menu, adding where missing and removing from all", async () => {
    const A = "tag_aaaaaaaa";
    const tags = [{ id: A, name: "待核实", color: "#e5484d", meaning: "" }, { id: "tag_bbbbbbbb", name: "未付款", color: "#3e63dd", meaning: "" }];
    const one = "1".repeat(20);
    const two = "2".repeat(20);
    const row = (key: string, number: string, format: string) => ({ invoice_key: key, source_path: `/合成/甲/成本发票/${key}.${format}`, source_file: `${key}.${format}`,
      file_format: format.toUpperCase(), invoice_number: number, seller: "丙丁", buyer: "甲", amount: "1130.00", tags: number === one ? [A] : [] });
    // Two formats of one invoice share a number; one row has no number at all.
    const rows = [row("1", one, "pdf"), row("2", one, "xml"), row("3", two, "pdf"), row("4", "", "pdf")];
    const directory = { ...DIRECTORIES[0]!, projection: { ...DIRECTORIES[0]!.projection, summary_exists: true } };
    const metric = { value: 0, valid_invoice_count: 0, conflict_invoice_count: 0, missing_invoice_count: 0 };
    let marks: Record<string, string[]> = { [one]: [A] };
    let revision = 7;
    stubBackend((url, init) => {
      const method = init.method ?? "GET";
      if (url === "/api/v1/invoice-tags") return [200, { ok: true, revision: 3, tags }];
      if (url.endsWith("/invoice-tags") && method === "GET") return [200, { ok: true, revision, invoices: marks }];
      if (url.endsWith("/invoice-tags")) {
        const changes = (JSON.parse(String(init.body)) as { changes: Record<string, string[]> }).changes;
        marks = { ...marks, ...changes };
        revision += 1;
        return [200, { ok: true, revision, invoices: Object.fromEntries(Object.entries(marks).filter(([, ids]) => ids.length)) }];
      }
      if (url.includes("/invoices?")) return [200, { ok: true, count: 4, page: 1, page_size: 50, read_only: false, directory, items: rows, snapshot: { provisional: false } }];
      if (url.endsWith("/selection-summary")) return [200, { ok: true, selection: { record_count: 4, invoice_count: 3, collapsed_record_count: 1 },
        totals: { pretax_amount: metric, tax_amount: metric, total_with_tax: metric }, cost_breakdown: {} }];
      return undefined;
    });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const wrapper = await mountCompanies();
    await wrapper.findAll("button").find((button) => button.text() === "查看发票")!.trigger("click");
    await flushPromises();
    const list = wrapper.get('[aria-label="目录发票"]');
    await list.get('input[aria-label="勾选本页"]').setValue(true);
    vi.advanceTimersByTime(300);
    await flushPromises();
    // Batch tagging adds nothing to what the selection actions send.
    expect(calls.find((call) => call.url.endsWith("/selection-summary"))!.body).toEqual({ items: rows.map((item) => ({ invoice_key: item.invoice_key, source_path: item.source_path })) });

    await list.findAll("tbody tr")[2]!.trigger("keydown", { key: "F10", shiftKey: true });
    await flushPromises();
    const menu = () => wrapper.get('[role="menu"][aria-label="已勾选 4 张发票的标签"]');
    expect(menu().text()).toContain("2 个发票号码");
    expect(menu().text()).toContain("其中 1 张没有发票号码");
    const box = () => menu().findAll('[role="menuitemcheckbox"]')[0]!.get("input");
    expect(menu().get('[role="menuitemcheckbox"]').attributes("aria-checked")).toBe("mixed");
    expect((box().element as HTMLInputElement).indeterminate).toBe(true);

    await box().setValue(true);
    await flushPromises();
    const puts = () => calls.filter((call) => call.method === "PUT");
    expect(puts()[0]!.body).toEqual({ revision: 7, changes: { [two]: [A] } }); // only where it was missing
    expect(menu().get('[role="menuitemcheckbox"]').attributes("aria-checked")).toBe("true");
    expect(list.findAll("tbody tr")[2]!.find(".tag-dot").exists()).toBe(true); // dots updated in place

    await box().setValue(false);
    await flushPromises();
    expect(puts()[1]!.body).toEqual({ revision: 8, changes: { [one]: [], [two]: [] } }); // all had it: removed from all
    expect(list.findAll("tbody .tag-dot")).toHaveLength(0);
    expect(calls.filter((call) => call.url.includes("/invoices?")).length).toBe(1); // no reload
    // A row outside the selection still tags only itself.
    await list.get('input[aria-label="勾选 ' + two + '"]').setValue(false);
    await list.findAll("tbody tr")[2]!.trigger("keydown", { key: "F10", shiftKey: true });
    expect(wrapper.get('[role="menu"]').attributes("aria-label")).toBe(`${two} 的标签`);
    vi.useRealTimers();
  });

  it("offers no selection on a non-monitored folder", async () => {
    stubBackend((url) => (url.includes("/directories?") || url.endsWith("/directories")
      ? [200, { ok: true, revision: 3, company: COMPANY, directories: [{ ...DIRECTORIES[1], status: "present" }] }] : undefined));
    const wrapper = await mountCompanies();
    await wrapper.get(".row-actions button").trigger("click");
    await flushPromises();
    expect(wrapper.find('[aria-label="目录发票"] input[type="checkbox"]').exists()).toBe(false);
  });

  it("edits a voucher draft, shows the live balance and keeps refused approvals on the page", async () => {
    const NAME = "凭证草稿_2026-06_2026-06.xlsx";
    const line = (row: number, code: string, debit: string | null, credit: string | null) =>
      ({ row, summary: "付丙丁材料款", code, name: code === "2202" ? "应付账款" : "银行存款", debit, credit, supplier: "", qty: null, unit: "", todo: "", confidence: "高", basis: "" });
    const voucher = { month: "2026-06", number: "002", date: "2026-06-30", approval: "", debit_total: "900.00", credit_total: "800.00",
      errors: ["借贷不平衡：借 900.00 贷 800.00"], warnings: [], lines: [line(4, "2202", "900.00", null), line(5, "1002", null, "800.00")] };
    const payload = { ok: true, name: NAME, revision: "r1", books_error: "", vouchers: [voucher], approved: 0, blocked: 1 };
    let refuse = true;
    stubBackend((url, init) => {
      if (url.endsWith("/voucher-drafts")) return [200, { ok: true, drafts: [{ name: NAME }] }];
      if (url.includes("/voucher-drafts/") && (init.method ?? "GET") === "GET") return [200, payload];
      if (url.includes("/voucher-drafts/") && refuse) return [422, { ok: false, detail: "x", error: { code: "VOUCHER_DRAFT_NOT_APPROVABLE", message: "x",
        details: [{ month: "2026-06", number: "002", errors: ["科目 9999 不存在、未启用或不是末级"] }] } }];
      if (url.includes("/voucher-drafts/")) return [200, { ...payload, revision: "r2", vouchers: [{ ...voucher, approval: "通过", errors: [], credit_total: "900.00" }], approved: 1, blocked: 0, saved_rows: 1, saved_approvals: 1 }];
      return undefined;
    });
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-vouchers").trigger("click");
    await flushPromises();
    const card = () => wrapper.get('[aria-label="2026-06 第 002 号凭证"]');
    expect(card().text()).toContain("借 900.00 · 贷 800.00 · 不平");
    expect(card().text()).toContain("借贷不平衡");
    await card().get('input[aria-label="第 5 行贷方"]').setValue("900");
    expect(card().get(".voucher__totals").text()).toBe("借 900.00 · 贷 900.00");
    expect(card().text()).toContain("保存后重新校验");
    await card().get("select").setValue("通过");
    await wrapper.findAll("button").find((button) => button.text().startsWith("保存（1 张）"))!.trigger("click");
    await flushPromises();
    const put = calls.find((call) => call.method === "PUT")!;
    expect(put.body).toEqual({ revision: "r1", vouchers: [{ month: "2026-06", number: "002", approval: "通过", lines: [{ row: 5, credit: "900" }] }] });
    // Refused: nothing saved, the edit and the backend's reason stay visible.
    expect(card().text()).toContain("科目 9999 不存在");
    expect((card().get('input[aria-label="第 5 行贷方"]').element as HTMLInputElement).value).toBe("900");
    refuse = false;
    await wrapper.findAll("button").find((button) => button.text().startsWith("保存（1 张）"))!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("已保存：改动 1 行、审核状态 1 张");
    expect((card().get("select").element as HTMLSelectElement).value).toBe("通过");
  });

  it("moves a voucher to another period with its month-end date and shows the draft's check sheets", async () => {
    const NAME = "凭证草稿_2026-06_2026-06.xlsx";
    const line = (row: number, code: string) => ({ row, summary: "付款", code, name: "", debit: row === 2 ? "10.00" : null, credit: row === 3 ? "10.00" : null,
      supplier: "", qty: null, unit: "", todo: "", confidence: "高", basis: "" });
    const voucher = { month: "2026-06", number: "002", date: "2026-06-30", approval: "通过", debit_total: "10.00", credit_total: "10.00", errors: [], warnings: [], lines: [line(2, "2202"), line(3, "1002")] };
    const sheets = [{ name: "库存核对", columns: ["月份", "品名", "期末数量"], rows: [["2026-06", "螺纹钢", 7.5]], truncated: false }];
    const payload = { ok: true, name: NAME, revision: "r1", books_error: "", vouchers: [voucher], approved: 1, blocked: 0, sheets, current_month: "2026-11" };
    stubBackend((url, init) => {
      if (url.endsWith("/voucher-drafts")) return [200, { ok: true, drafts: [{ name: NAME }] }];
      if (url.includes("/voucher-drafts/") && (init.method ?? "GET") === "GET") return [200, payload];
      if (url.includes("/voucher-drafts/")) return [200, { ...payload, revision: "r2", vouchers: [{ ...voucher, month: "2026-05", number: "001", date: "2026-05-31", approval: "" }],
        saved_rows: 0, saved_approvals: 0, moved: [{ from: { month: "2026-06", number: "002" }, to: { month: "2026-05", number: "001" } }] }];
      return undefined;
    });
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-vouchers").trigger("click");
    await flushPromises();
    expect(wrapper.get('table[aria-label="库存核对"]').text()).toContain("7.5");
    const card = wrapper.get('[aria-label="2026-06 第 002 号凭证"]');
    expect(card.get('input[aria-label="2026-06 第 002 号凭证所属期"]').attributes("max")).toBe("2026-11");
    await card.get('input[aria-label="2026-06 第 002 号凭证所属期"]').setValue("2026-05");
    await card.get('input[aria-label="2026-06 第 002 号凭证所属期"]').trigger("change");
    expect((card.get('input[aria-label="2026-06 第 002 号凭证记账日期"]').element as HTMLInputElement).value).toBe("2026-05-31");
    expect(card.text()).toContain("保存后移到 2026-05");
    await wrapper.findAll("button").find((button) => button.text().startsWith("保存（1 张）"))!.trigger("click");
    await flushPromises();
    expect(calls.find((call) => call.method === "PUT")!.body).toEqual({ revision: "r1", vouchers: [{ month: "2026-06", number: "002", move_month: "2026-05", date: "2026-05-31", lines: [] }] });
    expect(wrapper.text()).toContain("移动后重新编号：2026-06 第 002 号 → 2026-05 第 001 号");
  });

  it("exports the approved vouchers only after a confirm with the preparer and reports blocked months", async () => {
    const NAME = "凭证草稿_2026-06_2026-06.xlsx";
    const line = (row: number) => ({ row, summary: "付款", code: "1002", name: "", debit: row === 2 ? "10.00" : null, credit: row === 3 ? "10.00" : null,
      supplier: "", qty: null, unit: "", todo: "", confidence: "高", basis: "" });
    const voucher = (month: string, number: string) => ({ month, number, date: `${month}-30`, approval: "通过", debit_total: "10.00", credit_total: "10.00", errors: [], warnings: [], lines: [line(2), line(3)] });
    const payload = { ok: true, name: NAME, revision: "r1", books_error: "", vouchers: [voucher("2026-05", "001"), voucher("2026-06", "001")], approved: 2, blocked: 0, sheets: [], current_month: "2026-11" };
    stubBackend((url, init) => {
      if (url.endsWith("/voucher-drafts")) return [200, { ok: true, drafts: [{ name: NAME }] }];
      if (url.endsWith("/export")) return [200, { ok: true, name: NAME, files: ["捷锐导入_2026-05_20261113_101010.xlsx"], exported: 1, skipped: 1, learned: 0,
        errors: [{ voucher: "2026-06 第001号", errors: ["第 3 行 科目 1002 不存在、未启用或不是末级"] }], blocked_months: ["2026-06"], warnings: [], duplicates: [] }];
      if (url.includes("/voucher-drafts/") && (init.method ?? "GET") === "GET") return [200, payload];
      return undefined;
    });
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-vouchers").trigger("click");
    await flushPromises();
    const exportButton = () => wrapper.findAll("button").find((button) => button.text() === "导出已审核…")!;
    // Unsaved edits: export would not include them, so it waits for a save.
    await wrapper.get('input[aria-label="第 2 行摘要"]').setValue("改过");
    expect(exportButton().attributes("disabled")).toBeDefined();
    await wrapper.get('input[aria-label="第 2 行摘要"]').setValue("付款");
    await wrapper.findAll("button").find((button) => button.text() === "重新读取")!.trigger("click");
    await flushPromises();
    await exportButton().trigger("click");
    const panel = wrapper.get('[aria-label="导出已审核凭证"]');
    const confirm = () => panel.findAll("button").find((button) => button.text() === "确认导出")!;
    expect(confirm().attributes("disabled")).toBeDefined(); // 制单人 is required
    expect(calls.some((call) => call.url.endsWith("/export"))).toBe(false);
    await panel.get('input[aria-label="2026-06 账套已用到的凭证号"]').setValue("5");
    await panel.get('input[aria-label="制单人"]').setValue("张三");
    await confirm().trigger("click");
    await flushPromises();
    expect(calls.find((call) => call.url.endsWith("/export"))!.body).toEqual({ revision: "r1", preparer: "张三", after: { "2026-06": 5 }, confirm: true });
    const result = wrapper.get('[aria-label="导出结果"]');
    expect(result.text()).toContain("做账草稿/捷锐导入_2026-05_20261113_101010.xlsx");
    expect(result.text()).toContain("2026-06 整月未导出");
  });

  it("generates a draft from the page with the listed read-backs and shows what needs a new review", async () => {
    const NAME = "凭证草稿_2026-07_2026-09.xlsx";
    const inputs = { booked: ["序时账_2026-06.txt"], ledgers: ["科目表_2026-10-01.json", "科目表_2026-10-20.json"], tax_file: true, current_month: "2026-11" };
    let generated = false;
    stubBackend((url, init) => {
      const method = init.method ?? "GET";
      if (url.endsWith("/voucher-drafts") && method === "POST") {
        generated = true;
        return [200, { ok: true, name: NAME, tax_file_created: false, vouchers: 12, low_confidence: 1, missing_accounts: 0, backup: "历史/凭证草稿_2026-07_2026-09_20261113_101010.xlsx",
          carried: { kept: ["2026-07 第 001 号 购钢材-林函"], review_again: ["2026-08 第 003 号 销售钢材-银洲"], new: [], gone: [], summaries_kept: 2 } }];
      }
      if (url.endsWith("/voucher-drafts")) return [200, { ok: true, drafts: generated ? [{ name: NAME }] : [], inputs }];
      if (url.includes("/voucher-drafts/")) return [200, { ok: true, name: NAME, revision: "r1", books_error: "", vouchers: [], approved: 0, blocked: 0, sheets: [], current_month: "2026-11" }];
      return undefined;
    });
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-vouchers").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("点“生成草稿…”生成");
    await wrapper.findAll("button").find((button) => button.text() === "生成草稿…")!.trigger("click");
    const panel = wrapper.get('[aria-label="生成凭证草稿"]');
    expect(panel.get('input[aria-label="结束月份"]').attributes("max")).toBe("2026-11");
    expect((panel.get('select[aria-label="科目表"]').element as HTMLSelectElement).value).toBe("科目表_2026-10-20.json"); // newest snapshot
    await panel.get('input[aria-label="起始月份"]').setValue("2026-07");
    await panel.get('input[aria-label="结束月份"]').setValue("2026-09");
    await panel.findAll("button").find((button) => button.text() === "生成")!.trigger("click");
    await flushPromises();
    expect(calls.find((call) => call.method === "POST" && call.url.endsWith("/voucher-drafts"))!.body).toEqual({
      from: "2026-07", to: "2026-09", month_end: true, booked: ["序时账_2026-06.txt"], ledger: "科目表_2026-10-20.json", confirm: true,
    });
    const result = wrapper.get('[aria-label="生成结果"]');
    expect(result.text()).toContain("旧表已备份到 做账草稿/历史/");
    expect(result.text()).toContain("沿用审核 1 张、沿用改过的摘要 2 行");
    expect(result.text()).toContain("需要重新审核 1 张");
    expect(calls.some((call) => call.url.endsWith(`/voucher-drafts/${encodeURIComponent(NAME)}`))).toBe(true); // the new table is opened
  });

  it("rebooks an invoice to another period, regenerates and shows it as cross-period", async () => {
    const NAME = "凭证草稿_2026-07_2026-08.xlsx";
    const number = "1".repeat(12) + "87654321";
    const line = (row: number) => ({ row, summary: "购钢材", code: "1405", name: "", debit: row === 2 ? "10.00" : null, credit: row === 3 ? "10.00" : null,
      supplier: "", qty: null, unit: "", todo: "", confidence: "高", basis: "" });
    const doc = (month: string, override: { month: string; reason: string } | null) =>
      ({ kind: "进项发票", number, issue_date: "2026-07-10", book_month: month, cross: month !== "2026-07", movable: true, override });
    const voucher = (month: string, override: { month: string; reason: string } | null) =>
      ({ month, number: "001", date: `${month}-30`, approval: "", debit_total: "10.00", credit_total: "10.00", errors: [], warnings: [], lines: [line(2), line(3)], source_documents: [doc(month, override)] });
    const bank = { ...voucher("2026-07", null), number: "002", source_documents: [{ kind: "银行流水", number: "", issue_date: "", book_month: "2026-07", cross: false, movable: false, override: null }] };
    let moved = false;
    const payload = () => ({ ok: true, name: NAME, revision: "r1", books_error: "", approved: 0, blocked: 0, sheets: [], current_month: "2026-11",
      periods_revision: moved ? 5 : 4, cross_period_hint: "跨期常见原因：次月到票",
      vouchers: [moved ? voucher("2026-08", { month: "2026-08", reason: "次月到票" }) : voucher("2026-07", null), bank] });
    stubBackend((url, init) => {
      if (url.endsWith("/rebook")) {
        moved = true;
        return [200, { ok: true, periods_revision: 5, generation_remembered: true, out_of_range: false,
          generated: { name: NAME, tax_file_created: false, vouchers: 2, low_confidence: 0, missing_accounts: 0, backup: "历史/x.xlsx", carried: { kept: [], review_again: [], new: [], gone: [], summaries_kept: 0 } } }];
      }
      if (url.endsWith("/voucher-drafts")) return [200, { ok: true, drafts: [{ name: NAME }], inputs: { booked: [], ledgers: [], tax_file: true, current_month: "2026-11" } }];
      if (url.includes("/voucher-drafts/") && (init.method ?? "GET") === "GET") return [200, payload()];
      return undefined;
    });
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-vouchers").trigger("click");
    await flushPromises();
    const card = () => wrapper.get('[aria-label="2026-07 第 001 号凭证"], [aria-label="2026-08 第 001 号凭证"]');
    expect(card().get(".voucher__source").text()).toContain("开票 2026-07-10");
    expect(card().get(".voucher__source .tag").text()).toBe("同期");
    expect(wrapper.get('[aria-label="2026-07 第 002 号凭证"] .voucher__source').text()).toContain("不能单独改记入期");
    await card().findAll("button").find((button) => button.text() === "改记入期")!.trigger("click");
    const group = wrapper.get('[aria-label="改记入期 2026-07 第 001 号凭证"]');
    await group.get('input[aria-label="记入期"]').setValue("2026-08");
    await group.findAll("button").find((button) => button.text() === "保存并重新生成")!.trigger("click");
    await flushPromises();
    expect(calls.find((call) => call.url.endsWith("/rebook"))!.body).toEqual({ revision: 4, number, month: "2026-08", reason: "次月到票" });
    expect(wrapper.text()).toContain("已改记入 2026-08，草稿已重新生成");
    expect(card().attributes("aria-label")).toBe("2026-08 第 001 号凭证");
    expect(card().get(".voucher__source .tag").text()).toBe("跨期");
    expect(card().get(".voucher__source").text()).toContain("人工调整记入期（次月到票）");
  });

  it("checks period folders by content and moves a misfiled file only after the confirm", async () => {
    const check = { folders: [{ name: "5月", period: "5 月" }, { name: "6月", period: "6 月" }], mismatched: 1, items: [
      { file: "6月/用途确认信息 (1).xlsx", name: "用途确认信息 (1).xlsx", folder: "6月", folder_period: "6 月", content_period: "2026-07", status: "mismatch", target: "2026-07", target_exists: false },
      { file: "5月/用途确认信息.xlsx", name: "用途确认信息.xlsx", folder: "5月", folder_period: "5 月", content_period: "2026-05", status: "ok", target: "", target_exists: false },
    ] };
    const plan = { job_id: "a".repeat(32), state: "prepared", moved_count: 0, files: [{ file: "6月/用途确认信息 (1).xlsx", target: "2026-07", new_folder: true, status: "pending", message: "" }] };
    stubBackend((url) => {
      if (url.includes("/period-folders?")) return [200, { ok: true, ...check }];
      if (url.endsWith("/period-folders/moves")) return [200, { ok: true, ...plan }];
      if (url.endsWith("/confirm")) return [503, { detail: "连接中断" }];
      if (url.includes("/period-folders/moves/")) return [200, { ok: true, ...plan, state: "completed", moved_count: 1, files: [{ ...plan.files[0], status: "moved" }] }];
      return undefined;
    });
    setActivePinia(createPinia());
    const wrapper = mount(PeriodFolderCheck, { props: { company: COMPANY as Company, dirKey: "input_deduction_dir" }, attachTo: document.body });
    await flushPromises();
    expect(wrapper.text()).toContain("1 个文件可能放错了属期文件夹");
    expect(wrapper.findAll('[aria-label="属期文件"] tbody tr')).toHaveLength(1); // only what needs attention by default
    const select = wrapper.get('select[aria-label="6月/用途确认信息 (1).xlsx 移到"]');
    expect(select.text()).toContain("2026-07（建议）（新建）");
    await select.setValue("2026-07");
    await wrapper.findAll("button").find((button) => button.text().startsWith("移动所选…"))!.trigger("click");
    await flushPromises();
    expect(calls.find((call) => call.url.endsWith("/moves"))!.body).toEqual({ key: "input_deduction_dir", items: [{ file: "6月/用途确认信息 (1).xlsx", target: "2026-07" }] });
    expect(calls.some((call) => call.url.endsWith("/confirm"))).toBe(false); // nothing moves before the confirm
    expect(wrapper.get('[aria-label="确认移动文件"]').text()).toContain("6月/用途确认信息 (1).xlsx → 2026-07/");
    await wrapper.get('[aria-label="确认移动文件"]').findAll("button").find((button) => button.text() === "确认移动")!.trigger("click");
    await flushPromises();
    // The confirm response was lost: the journal is read, the confirm is never sent twice.
    expect(calls.filter((call) => call.url.endsWith("/confirm"))).toHaveLength(1);
    expect(wrapper.get('[aria-label="移动结果"]').text()).toContain("已移动 1 / 1 个文件");
    wrapper.unmount();
  });

  it("shows the bureau's social insurance table, masks people and confirms a month into the tax file", async () => {
    const side = (due: string | null) => ({ count: due ? 1 : null, wage: due ? "4952.00" : null, base: due ? "4952.00" : null, rate: due ? "16%" : null, due });
    const month = { month: "2026-08", source: "8月社保.xlsx", unit_total: "792.32", personal_total: "396.16", total: "1188.48", checks_ok: false, rows: [
      { insurance: "城镇职工基本养老保险", total: "1200.00", unit: side("792.32"), personal: side("396.16"),
        checks: [{ code: "total", ok: false, message: "城镇职工基本养老保险：单位 792.32 + 个人 396.16 = 合计 1200.00" }] },
    ] };
    let reveal = false;
    const payroll = () => ({ ok: true, folder: "工资社保", folder_present: true, tax_file: true, tax_revision: "t1", people_masked: !reveal,
      files: [{ file: "9月社保缴纳.png", kind: "image", status: "skipped", message: "图片需要 OCR，本版本暂不识别" }],
      months: [month], confirmed: {}, people: [{ name: reveal ? "张小三" : "张*三", id_number: reveal ? "320681199001011234" : "320***********1234", base: "4952.00", month: "2026-08" }] });
    stubBackend((url, init) => {
      if (url.includes("/payroll") && (init.method ?? "GET") === "PUT") return [200, { ok: true, saved: ["2026-08"], tax_revision: "t2" }];
      if (url.includes("/payroll")) {
        reveal = url.includes("reveal=true");
        return [200, payroll()];
      }
      return undefined;
    });
    const wrapper = await mountCompanies();
    await wrapper.get("#company-tab-payroll").trigger("click");
    await flushPromises();
    const table = wrapper.get('[aria-label="2026-08 社保费应缴明细"]');
    expect(table.findAll("thead tr")[0]!.text()).toContain("单位部分");
    expect(table.get("tbody tr").classes()).toContain("row--failed");
    expect(table.text()).toContain("核对不成立");
    expect(wrapper.text()).toContain("9月社保缴纳.png：图片需要 OCR");
    expect(wrapper.get('[aria-label="人员明细"]').text()).toContain("张*三");
    await wrapper.get('[aria-label="工资社保"] input[type="checkbox"]').setValue(true);
    await flushPromises();
    expect(calls.some((call) => call.url.endsWith("/payroll?reveal=true"))).toBe(true);
    expect(wrapper.get('[aria-label="人员明细"]').text()).toContain("张小三");
    await wrapper.get('[aria-label="2026-08 社保费应缴明细"]').findAll("button").find((button) => button.text() === "确认写入申报数据")!.trigger("click");
    await flushPromises();
    expect(calls.find((call) => call.method === "PUT")!.body).toEqual({ revision: "t1", months: { "2026-08": { rows: month.rows, source: "8月社保.xlsx" } } });
    expect(wrapper.text()).toContain("已确认 2026-08 社保：单位 792.32、个人 396.16");
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
