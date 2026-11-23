import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import DirectorySelectionBar from "../src/components/DirectorySelectionBar.vue";
import DirectoryPanel from "../src/components/DirectoryPanel.vue";
import CompanyCreateForm from "../src/components/CompanyCreateForm.vue";
import CompanyDirectories from "../src/components/CompanyDirectories.vue";
import CompanyPanel from "../src/components/CompanyPanel.vue";
import type { Company } from "../src/api/types";
import { useCompaniesStore } from "../src/stores/companies";

const respond = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const COMPANY: Company = {
  id: "co_1",
  name: "合成测试公司",
  root_dir: "/合成/甲",
  root_path: "/合成/甲",
  root_status: "present",
  subdirs: [
    { key: "cost_invoice_dir", label: "成本发票", relative_path: "成本发票", path: "/合成/甲/成本发票", status: "present" },
    { key: "issued_invoice_dir", label: "开具发票", relative_path: "开具发票", path: "/合成/甲/开具发票", status: "present" },
  ],
  missing_subdir_count: 0,
  taxpayer_periods: [],
  current_taxpayer_type: "general",
  current_taxpayer_label: "一般纳税人",
  monitored: false,
  monitored_subdir_key: null,
};

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("selection summary details modal", () => {
  it("opens a wide modal with item/spec breakdown, filters by keyword and tax rate without altering headline totals, and previews a source invoice", async () => {
    vi.useFakeTimers();
    const breakdownPayload = {
      ok: true,
      selection: { record_count: 3, invoice_count: 2, collapsed_record_count: 1 },
      totals: {
        pretax_amount: { value: 1500, valid_invoice_count: 2, conflict_invoice_count: 0, missing_invoice_count: 0 },
        tax_amount: { value: 165, valid_invoice_count: 2, conflict_invoice_count: 0, missing_invoice_count: 0 },
        total_with_tax: { value: 1665, valid_invoice_count: 2, conflict_invoice_count: 0, missing_invoice_count: 0 },
      },
      cost_breakdown: {
        available: true,
        matched_invoice_count: 2,
        unmatched_invoice_count: 0,
        detail_count: 2,
        projects: [
          {
            project_name: "螺纹钢",
            display_project_name: "螺纹钢",
            tax_rate: "13%",
            display_tax_rate: "13%",
            quantity_total: 10,
            amount_pretax_total: 1000,
            total_with_tax: 1130,
            specs: [
              {
                specification: "HRB400E 18",
                unit: "吨",
                quantity_total: 10,
                arithmetic_average_unit_price_pretax: 100,
                arithmetic_average_unit_price_with_tax: 113,
                weighted_average_unit_price_pretax: 100,
                weighted_average_unit_price_with_tax: 113,
              },
            ],
            source_invoices: [
              { invoice_key: "k1", source_path: "/watch/a.pdf", file_name: "a.pdf", invoice_number: "10000000000000000001", target_id: "t1" },
            ],
          },
          {
            project_name: "运费服务",
            display_project_name: "运费服务",
            tax_rate: "9%",
            display_tax_rate: "9%",
            quantity_total: 1,
            amount_pretax_total: 500,
            total_with_tax: 545,
            specs: [
              {
                specification: "短途运输",
                unit: "次",
                quantity_total: 1,
                arithmetic_average_unit_price_pretax: 500,
                arithmetic_average_unit_price_with_tax: 545,
                weighted_average_unit_price_pretax: 500,
                weighted_average_unit_price_with_tax: 545,
              },
            ],
            source_invoices: [
              { invoice_key: "k2", source_path: "/watch/b.pdf", file_name: "b.pdf", invoice_number: "10000000000000000002", target_id: "t1" },
            ],
          },
        ],
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => respond(breakdownPayload)));

    const wrapper = mount(DirectorySelectionBar, {
      attachTo: document.body,
      props: {
        items: [
          { invoice_key: "k1", source_path: "/watch/a.pdf" },
          { invoice_key: "k2", source_path: "/watch/b.pdf" },
        ],
        targetId: "t1",
        total: 2,
        selectingAll: false,
      },
    });
    await vi.advanceTimersByTimeAsync(260);
    await flushPromises();

    await wrapper.get(".sb-sum").trigger("click");
    await flushPromises();

    const modal = document.body.querySelector('[role="dialog"][aria-label="已勾选发票合计详情"]')!;
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain("1,665.00");
    expect(modal.textContent).toContain("螺纹钢");
    expect(modal.textContent).toContain("HRB400E 18");
    expect(modal.textContent).toContain("运费服务");
    expect(modal.textContent).toContain("显示 2 / 2 个项目税率分组");

    // Filter by tax rate: narrows breakdown list but preserves full headline totals.
    const rateSelect = modal.querySelector('select[aria-label="按税率筛选"]') as HTMLSelectElement;
    rateSelect.value = "13%";
    rateSelect.dispatchEvent(new Event("change"));
    await flushPromises();
    expect(modal.textContent).toContain("显示 1 / 2 个项目税率分组");
    expect(modal.textContent).toContain("螺纹钢");
    expect(modal.textContent).not.toContain("短途运输");
    expect(modal.textContent).toContain("1,665.00");

    // Search by specification and click source invoice button.
    const searchInput = modal.querySelector('input[aria-label="搜索明细"]') as HTMLInputElement;
    searchInput.value = "HRB400E";
    searchInput.dispatchEvent(new Event("input"));
    await flushPromises();
    const sourceBtn = modal.querySelector(".sum-sources li button") as HTMLButtonElement;
    sourceBtn.click();
    await flushPromises();
    expect(wrapper.emitted("previewItem")).toEqual([[{ invoice_key: "k1", source_path: "/watch/a.pdf" }]]);
    expect(document.body.querySelector('[role="dialog"][aria-label="已勾选发票合计详情"]')).toBeNull();
    wrapper.unmount();
  });
});

describe("non-monitored directory read-only data refresh", () => {
  it("triggers read-only refresh from DirectoryPanel and reloads when completed", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useCompaniesStore().list = { ok: true, revision: 1, companies: [COMPANY], monitored_company_id: null, target_id: "t0", watch_dir: "/other", standard_subdirs: [] };
    let refreshed = false;
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push(`${init.method ?? "GET"} ${url}`);
      if (url.endsWith("/refresh-data") && init.method === "POST") {
        refreshed = true;
        return respond({ ok: true, company_id: "co_1", job_id: "j1", status: "completed", keys: ["cost_invoice_dir"], current_key: "", current_label: "", message: "发票数据已读取完成，现在可以直接查看。", directories: {}, updated_at: "" });
      }
      if (url.endsWith("/directories")) {
        return respond({
          ok: true,
          revision: 1,
          company: COMPANY,
          directories: [{
            ...COMPANY.subdirs[0],
            target_id: "t_cost",
            active: false,
            read_only: true,
            projection: { summary_exists: refreshed, summary_updated_at: refreshed ? "2026-11-23 16:50:00" : "", cost_detail_exists: refreshed, cost_detail_updated_at: "" },
            freshness: { state: refreshed ? "fresh" : "never_built", message: refreshed ? "已是最新数据。" : "还没读取过数据" },
          }],
        });
      }
      if (url.includes("/invoices")) {
        return respond({
          ok: true, company_id: "co_1", directory_key: "cost_invoice_dir", read_only: true, count: refreshed ? 1 : 0, page: 1, page_size: 50,
          items: refreshed ? [{ invoice_key: "k1", source_path: "/合成/甲/成本发票/a.xml", source_file: "a.xml", file_format: "XML", seller: "供应甲", buyer: "合成测试公司", invoice_number: "10000000000000000001", invoice_type: "增值税专用发票", business_type: "标准电子发票", tax_rate: "0.13", amount: "113.00", invoice_date: "2026-09-10", status: "已识别", tags: [] }] : [],
          stats: { all: { total: refreshed ? 1 : 0, recognized: refreshed ? 1 : 0, needs_review: 0, duplicates: 0 }, filtered: { total_amount: refreshed ? "113.00" : "0.00", total_amount_valid_count: refreshed ? 1 : 0 } },
          snapshot: { revision: refreshed ? 2 : 1, provisional: false },
          directory: { target_id: "t_cost", projection: { summary_exists: refreshed } },
        });
      }
      if (url.endsWith("/invoice-tags")) return respond({ ok: true, revision: 1, tags: [] });
      return respond({ ok: true });
    }));

    const wrapper = mount(DirectoryPanel, {
      global: { plugins: [pinia] },
      props: { company: COMPANY, dirKey: "cost_invoice_dir" },
    });
    await flushPromises();
    const readBtn = wrapper.findAll("button").find((btn) => btn.text() === "读取数据")!;
    expect(readBtn).toBeDefined();
    await readBtn.trigger("click");
    await flushPromises();
    expect(calls.some((entry) => entry.startsWith("POST /api/v1/companies/co_1/refresh-data"))).toBe(true);
    expect(wrapper.text()).toContain("供应甲");
    wrapper.unmount();
  });

  it("shows parser-upgrade stale hint for non-monitored folders and lets active monitored folders run bridge rebuild", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const activeCompany: Company = { ...COMPANY, monitored: true, monitored_subdir_key: "cost_invoice_dir" };
    useCompaniesStore().list = { ok: true, revision: 1, companies: [activeCompany], monitored_company_id: "co_1", target_id: "t_cost", watch_dir: "/合成/甲/成本发票", standard_subdirs: [] };
    let rebuilt = false;
    const calls: string[] = [];
    const refreshedEvents: unknown[] = [];
    const onRefreshed = (e: Event) => refreshedEvents.push((e as CustomEvent).detail);
    window.addEventListener("workspace:company-refreshed", onRefreshed);

    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push(`${init.method ?? "GET"} ${url}`);
      if (url === "/api/v1/bridge/rebuild" && init.method === "POST") {
        rebuilt = true;
        return respond({ ok: true, task_id: "task-1", exit_code: 0, message: "汇总已完成，共 1 条发票，成本明细 4 行。" });
      }
      if (url.endsWith("/directories")) {
        return respond({
          ok: true,
          revision: 1,
          company: activeCompany,
          directories: [
            {
              ...COMPANY.subdirs[0],
              target_id: "t_cost",
              active: true,
              read_only: false,
              projection: { summary_exists: true, summary_updated_at: rebuilt ? "2026-11-23 23:20:00" : "2026-10-09 20:21:02", cost_detail_exists: true, cost_detail_updated_at: "" },
              freshness: { state: "monitored", message: "当前监控目录，新发票会自动读取。" },
            },
            {
              ...COMPANY.subdirs[1],
              target_id: "t_issued",
              active: false,
              read_only: true,
              projection: { summary_exists: true, summary_updated_at: "2026-10-09 20:21:02", cost_detail_exists: true, cost_detail_updated_at: "" },
              freshness: { state: "stale", parser_stale: true, added: 0, updated: 0, deleted: 0, message: "识别规则已更新，点“更新数据”即可重新汇总。" },
            },
          ],
        });
      }
      if (url.includes("/invoices")) {
        return respond({
          ok: true, company_id: "co_1", directory_key: "cost_invoice_dir", read_only: false, count: 1, page: 1, page_size: 50,
          items: [{ invoice_key: "k1", source_path: "/合成/甲/成本发票/oil.pdf", source_file: "oil.pdf", file_format: "PDF", seller: rebuilt ? "示例石油分公司" : "", buyer: "合成测试公司", invoice_number: "26327000000000000001", invoice_type: "增值税专用发票", business_type: rebuilt ? "成品油" : "标准电子发票", tax_rate: "13%", amount: "8800.00", invoice_date: "2026-07-29", status: "已识别", tags: [] }],
          stats: { all: { total: 1, recognized: 1, needs_review: 0, duplicates: 0 }, filtered: { total_amount: "8800.00", total_amount_valid_count: 1 } },
          snapshot: { revision: rebuilt ? 2 : 1, provisional: false },
          directory: { target_id: "t_cost", projection: { summary_exists: true } },
        });
      }
      if (url.endsWith("/invoice-tags")) return respond({ ok: true, revision: 1, tags: [] });
      return respond({ ok: true });
    }));

    const panel = mount(DirectoryPanel, {
      global: { plugins: [pinia] },
      props: { company: activeCompany, dirKey: "cost_invoice_dir" },
    });
    await flushPromises();
    const rebuildBtn = panel.findAll("button").find((btn) => btn.text() === "重新汇总")!;
    expect(rebuildBtn).toBeDefined();
    await rebuildBtn.trigger("click");
    await flushPromises();
    expect(calls).toContain("POST /api/v1/bridge/rebuild");
    expect(refreshedEvents.length).toBeGreaterThan(0);
    expect(panel.text()).toContain("示例石油分公司");
    expect(panel.text()).toContain("业务：成品油");
    panel.unmount();

    const dirTable = mount(CompanyDirectories, {
      global: { plugins: [pinia] },
      props: { company: activeCompany },
    });
    await flushPromises();
    expect(dirTable.text()).toContain("重新汇总");
    expect(dirTable.text()).toContain("（识别规则已更新）");
    dirTable.unmount();
    window.removeEventListener("workspace:company-refreshed", onRefreshed);
  });
});

describe("voucher list layout guard", () => {
  it("prevents flex compression on voucher list buttons so rows never overlap when scrolling", () => {
    const css = readFileSync(resolve(__dirname, "../src/prototype.css"), "utf-8");
    const match = /\.voucher-list button\s*\{([^}]+)\}/.exec(css);
    expect(match).not.toBeNull();
    expect(match![1]).toMatch(/flex:\s*0\s+0\s+auto|flex:\s*none|flex-shrink:\s*0/);
  });
});

describe("company registration month picker", () => {
  it("uses the calendar MonthPicker popover for taxpayer effective_from", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useCompaniesStore().list = { ok: true, revision: 1, companies: [], monitored_company_id: null, target_id: "t0", watch_dir: "/other", standard_subdirs: [] };
    const wrapper = mount(CompanyCreateForm, { attachTo: document.body, global: { plugins: [pinia] } });
    await wrapper.get('input[value="general"]').setValue(true);
    const trigger = wrapper.get('button[aria-label="生效月份"]');
    expect(trigger.text()).toContain("选择生效年月");
    await trigger.trigger("click");
    await flushPromises();
    const dialog = document.body.querySelector('[role="dialog"][aria-label="生效月份"]')!;
    expect(dialog).not.toBeNull();
    const june = [...dialog.querySelectorAll("button")].find((btn) => btn.textContent?.trim() === "6 月") as HTMLButtonElement;
    june.click();
    await flushPromises();
    expect(trigger.text()).toContain("6 月");
    wrapper.unmount();
  });
});

describe("single missing subfolder creation, in-tab back button, and overview tag layout", () => {
  it("previews and creates a single missing folder from CompanyDirectories", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const companyWithMissing: Company = {
      ...COMPANY,
      missing_subdir_count: 1,
      subdirs: [
        ...COMPANY.subdirs,
        { key: "expense_reimbursement_dir", label: "费用报销", relative_path: "费用报销", path: "/合成/甲/费用报销", status: "missing" },
      ],
    };
    useCompaniesStore().list = { ok: true, revision: 1, companies: [companyWithMissing], monitored_company_id: null, target_id: "t0", watch_dir: "/other", standard_subdirs: [] };
    const requests: { url: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      requests.push({ url, body: init.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith("/directories")) {
        return respond({
          ok: true, revision: 1, company: companyWithMissing,
          directories: companyWithMissing.subdirs.map((sub) => ({
            ...sub, target_id: `t_${sub.key}`, active: false, read_only: true,
            projection: { summary_exists: false, summary_updated_at: "", cost_detail_exists: false, cost_detail_updated_at: "" },
            freshness: { state: sub.status === "missing" ? "missing_dir" : "never_built", message: "" },
          })),
        });
      }
      if (url.includes("/subdirs/plan")) {
        return respond({ ok: true, company_id: "co_1", revision: 1, plan_hash: "single-hash", create_count: 1, blocked_count: 0, items: [{ key: "expense_reimbursement_dir", label: "费用报销", relative_path: "费用报销", path: "/合成/甲/费用报销", action: "create", reason: "" }] });
      }
      if (url.endsWith("/subdirs/create")) return respond({ ok: true, created: ["expense_reimbursement_dir"], skipped: [], failed: [] });
      return respond({ ok: true, revision: 2, companies: [companyWithMissing], monitored_company_id: null, target_id: "t0", watch_dir: "/other", standard_subdirs: [] });
    }));
    const wrapper = mount(CompanyDirectories, { global: { plugins: [pinia] }, props: { company: companyWithMissing } });
    await flushPromises();
    const createBtn = wrapper.findAll("button").find((btn) => btn.text() === "创建文件夹")!;
    expect(createBtn).toBeDefined();
    await createBtn.trigger("click");
    await flushPromises();
    expect(requests.some((req) => req.url.includes("/subdirs/plan?keys=expense_reimbursement_dir"))).toBe(true);
    await wrapper.get('[aria-label="补建预览"] button.primary').trigger("click");
    await flushPromises();
    expect(requests.find((req) => req.url.endsWith("/subdirs/create"))?.body).toEqual({
      plan_hash: "single-hash", confirm: true, keys: ["expense_reimbursement_dir"],
    });
    wrapper.unmount();
  });

  it("navigates back along in-tab section history in CompanyPanel", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useCompaniesStore().list = { ok: true, revision: 1, companies: [COMPANY], monitored_company_id: null, target_id: "t0", watch_dir: "/other", standard_subdirs: [] };
    vi.stubGlobal("fetch", vi.fn(async () => respond({ ok: true, directories: [], periods: [], projects: [], checks: [], checks_ok: true, warnings: [], totals: { input: { count: 0, pretax: "0.00", tax: "0.00", total: "0.00" }, output: { count: 0, pretax: "0.00", tax: "0.00", total: "0.00" }, face_difference_pretax: "0.00", face_difference_tax: "0.00" } })));
    const wrapper = mount(CompanyPanel, { global: { plugins: [pinia] }, props: { company: COMPANY } });
    await flushPromises();
    expect(wrapper.find('button[aria-label="返回上一页"]').exists()).toBe(false);
    await wrapper.get("#company-tab-directories").trigger("click");
    await wrapper.get("#company-tab-settings").trigger("click");
    const back = wrapper.get('button[aria-label="返回上一页"]');
    await back.trigger("click");
    expect(wrapper.get("#company-tab-directories").attributes("aria-selected")).toBe("true");
    await back.trigger("click");
    expect(wrapper.get("#company-tab-overview").attributes("aria-selected")).toBe("true");
    expect(wrapper.find('button[aria-label="返回上一页"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps OverviewDocuments status pills non-shrinking so long project names never truncate them", () => {
    const css = readFileSync(resolve(__dirname, "../src/prototype.css"), "utf-8");
    const match = /\.overview-doc__meta \.tag\s*\{([^}]+)\}/.exec(css);
    expect(match).not.toBeNull();
    expect(match![1]).toMatch(/flex:\s*0\s+0\s+auto|flex:\s*none|flex-shrink:\s*0/);
  });
});
