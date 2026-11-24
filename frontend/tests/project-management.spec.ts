import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CompanyProjects from "../src/components/CompanyProjects.vue";
import DirectoryInvoices from "../src/components/DirectoryInvoices.vue";
import type { Company, ProjectSummary } from "../src/api/types";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const COMPANY: Company = {
  id: "co_proj",
  name: "测试建工",
  root_dir: "/测试建工",
  root_path: "/测试建工",
  root_status: "present",
  missing_subdir_count: 0,
  monitored: false,
  monitored_subdir_key: null,
  current_taxpayer_type: "general",
  current_taxpayer_label: "一般纳税人",
  taxpayer_periods: [],
  subdirs: [
    { key: "cost_invoice_dir", label: "成本发票", relative_path: "成本发票", path: "/测试建工/成本发票", status: "present" },
    { key: "issued_invoice_dir", label: "开具发票", relative_path: "开具发票", path: "/测试建工/开具发票", status: "present" },
  ],
};

function summaryPayload(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    ok: true,
    basis_label: "票面口径",
    assignments_revision: 3,
    projects: [
      {
        project: "一期工程",
        unassigned: false,
        input: { count: 1, pretax: "1000.00", tax: "130.00", total: "1130.00" },
        output: { count: 0, pretax: "0.00", tax: "0.00", total: "0.00" },
        face_difference_pretax: "-1000.00",
        periods: [{ period: "2026-06", input_pretax: "1000.00", output_pretax: "0.00" }],
      },
      {
        project: "二期工程",
        unassigned: false,
        input: { count: 1, pretax: "500.00", tax: "65.00", total: "565.00" },
        output: { count: 0, pretax: "0.00", tax: "0.00", total: "0.00" },
        face_difference_pretax: "-500.00",
        periods: [{ period: "2026-06", input_pretax: "500.00", output_pretax: "0.00" }],
      },
    ],
    project_names: ["一期工程", "二期工程"],
    aliases: {},
    invoices: [
      {
        direction: "input",
        invoice_number: "10000000000000000001",
        invoice_date: "2026-06-05",
        counterpart: "丙丁建材",
        total: "1130.00",
        project: "一期工程",
        source: "remark",
        remark_projects: ["一期工程"],
        assignable: true,
        source_files: ["a.xml"],
      },
      {
        direction: "input",
        invoice_number: "10000000000000000002",
        invoice_date: "2026-06-08",
        counterpart: "戊己材料",
        total: "565.00",
        project: "二期工程",
        source: "manual",
        remark_projects: ["备注原名"],
        assignable: true,
        source_files: ["b.xml"],
      },
    ],
    unassigned_invoices: [],
    manual_invoices: [
      {
        direction: "input",
        invoice_number: "10000000000000000002",
        invoice_date: "2026-06-08",
        counterpart: "戊己材料",
        total: "565.00",
        project: "二期工程",
        source: "manual",
        remark_projects: ["备注原名"],
        assignable: true,
        source_files: ["b.xml"],
      },
    ],
    warnings: [],
    checks: [{ code: "input_total_ledger", ok: true, message: "一致" }],
    checks_ok: true,
    ...overrides,
  };
}

describe("project manual adjustment and renaming", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("allows manually reassigning remark invoices and explicitly moving to unassigned", async () => {
    const calls: { url: string; method: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url.includes("/projects/assignments") && method === "PUT") {
        return json({ ok: true, assignments_revision: 4, count: 2 });
      }
      return json(summaryPayload());
    }));

    const wrapper = mount(CompanyProjects, { props: { company: COMPANY } });
    await flushPromises();

    // Remark-detected invoice is visible and editable directly.
    const remarkInput = wrapper.get('[aria-label="10000000000000000001 项目"]');
    expect((remarkInput.element as HTMLInputElement).value).toBe("一期工程");
    await remarkInput.setValue("三期工程");

    // Second invoice can be explicitly moved to 未归属.
    const unassignButtons = wrapper.findAll("button").filter((btn) => btn.text() === "移出未归属");
    expect(unassignButtons.length).toBeGreaterThanOrEqual(2);
    await unassignButtons[1]!.trigger("click");

    await wrapper.get('form[aria-label="项目归属"]').trigger("submit");
    await flushPromises();

    const saveCall = calls.find((call) => call.method === "PUT" && call.url.includes("/projects/assignments"));
    expect(saveCall?.body).toEqual({
      revision: 3,
      assignments: { "10000000000000000001": "三期工程" },
      unassigned: ["10000000000000000002"],
    });
  });

  it("previews and confirms project rename with merge and service-cost sync", async () => {
    const calls: { url: string; method: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url.endsWith("/projects/rename/preview") && method === "POST") {
        return json({
          ok: true,
          company_id: "co_proj",
          revision: 3,
          from_name: "一期工程",
          to_name: "二期工程",
          manual_count: 0,
          remark_count: 1,
          stored_manual_count: 0,
          total_invoices: 1,
          merges_into_existing: true,
          sync_service_costs: true,
          service_cost_count: 2,
          service_costs_revision: 5,
          preview_hash: "a".repeat(64),
        });
      }
      if (url.endsWith("/projects/rename") && method === "POST") {
        return json({
          ok: true,
          from_name: "一期工程",
          to_name: "二期工程",
          assignments_revision: 4,
          manual_updated: 0,
          remark_count: 1,
          merges_into_existing: true,
          service_costs_updated: 2,
        });
      }
      return json(summaryPayload());
    }));

    const wrapper = mount(CompanyProjects, { props: { company: COMPANY }, attachTo: document.body });
    await flushPromises();

    await wrapper.get('[aria-label="重命名 一期工程"]').trigger("click");
    await flushPromises();

    const input = document.body.querySelector<HTMLInputElement>('[aria-label="新项目名称"]');
    expect(input).not.toBeNull();
    input!.value = "二期工程";
    input!.dispatchEvent(new Event("input"));
    await flushPromises();

    const previewBtn = [...document.body.querySelectorAll("button")].find((btn) => btn.textContent?.includes("预览影响"));
    previewBtn!.click();
    await flushPromises();

    expect(document.body.textContent).toContain("已存在，确认后两个项目的发票将合并汇总");
    expect(document.body.textContent).toContain("同时更新 2 条关联的服务成本记录");

    const confirmBtn = [...document.body.querySelectorAll("button")].find((btn) => btn.textContent?.includes("确认重命名"));
    confirmBtn!.click();
    await flushPromises();

    const confirmCall = calls.find((call) => call.url.endsWith("/projects/rename") && call.method === "POST");
    expect(confirmCall?.body).toMatchObject({
      revision: 3,
      from_name: "一期工程",
      to_name: "二期工程",
      sync_service_costs: true,
      service_costs_revision: 5,
      preview_hash: "a".repeat(64),
      confirm: true,
    });
    wrapper.unmount();
  });

  it("batch-assigns selected invoices from a non-monitored directory list", async () => {
    const calls: { url: string; method: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      if (url.includes("/api/v1/tags")) return json({ ok: true, revision: 1, tags: [] });
      if (url.includes("/directories/cost_invoice_dir/invoices")) {
        return json({
          ok: true,
          count: 1,
          page: 1,
          page_size: 50,
          read_only: true,
          directory: {
            key: "cost_invoice_dir",
            label: "成本发票",
            path: "/测试建工/成本发票",
            status: "present",
            target_id: "t1",
            monitored: false,
            projection: { summary_exists: true, count: 1, summary_updated_at: "", cost_detail_exists: true, cost_detail_updated_at: "" },
            freshness: { state: "fresh", message: "" },
          },
          items: [
            {
              invoice_key: "k1",
              source_path: "/测试建工/成本发票/a.xml",
              source_file: "a.xml",
              file_format: "XML",
              invoice_type: "增值税专用发票",
              invoice_number: "10000000000000000001",
              invoice_date: "2026-06-05",
              seller: "丙丁建材",
              buyer: "测试建工",
              amount: "1130.00",
              tax_rate: "13%",
              status: "已识别",
              project: "一期工程",
              project_source: "remark",
              tags: [],
            },
          ],
        });
      }
      if (url.includes("/projects/assignments") && method === "PUT") {
        return json({ ok: true, assignments_revision: 4, count: 1 });
      }
      if (url.includes("/projects")) return json(summaryPayload());
      return json({ ok: true });
    }));

    const wrapper = mount(DirectoryInvoices, {
      props: { company: COMPANY, dirKey: "cost_invoice_dir" },
      attachTo: document.body,
    });
    await flushPromises();

    expect(wrapper.text()).toContain("一期工程");
    await wrapper.get('[aria-label="勾选 10000000000000000001"]').setValue(true);
    await flushPromises();

    const assignBtn = wrapper.findAll("button").find((btn) => btn.text() === "调整项目…");
    expect(assignBtn).toBeTruthy();
    await assignBtn!.trigger("click");
    await flushPromises();

    const input = document.body.querySelector<HTMLInputElement>('[aria-label="项目名称"]');
    input!.value = "新归属项目";
    input!.dispatchEvent(new Event("input"));
    await flushPromises();

    const submit = [...document.body.querySelectorAll("button")].find((btn) => btn.textContent?.includes("确认保存"));
    submit!.click();
    await flushPromises();

    const putCall = calls.find((call) => call.method === "PUT" && call.url.includes("/projects/assignments"));
    expect(putCall?.body).toEqual({
      revision: 3,
      assignments: { "10000000000000000001": "新归属项目" },
    });
    wrapper.unmount();
  });
});
