import { DOMWrapper, flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import CompanyCreateForm from "../src/components/CompanyCreateForm.vue";
import CompanyDeleteModal from "../src/components/CompanyDeleteModal.vue";
import CompanySettings from "../src/components/CompanySettings.vue";
import DirectoryInvoices from "../src/components/DirectoryInvoices.vue";
import { useCompaniesStore } from "../src/stores/companies";
import type { Company, CompanySetupJob } from "../src/api/types";

const standards = [
  ["cost_invoice_dir", "成本发票"],
  ["issued_invoice_dir", "开具发票"],
  ["bank_flow_dir", "银行流水"],
  ["input_deduction_dir", "进项抵扣"],
  ["payroll_social_dir", "工资社保"],
  ["expense_reimbursement_dir", "费用报销"],
].map(([key, label]) => ({ key: key!, label: label! }));

const COMPANY: Company = {
  id: "co_1",
  name: "合成甲公司",
  root_dir: "/合成/甲公司",
  root_path: "/合成/甲公司",
  root_status: "present",
  subdirs: [
    ...standards.map((item) => ({
      ...item,
      default_label: item.label,
      relative_path: item.label,
      path: `/合成/甲公司/${item.label}`,
      status: "present" as const,
      kind: "standard" as const,
      role: item.key as Company["subdirs"][number]["role"],
    })),
    {
      key: "dir_1234567890ab",
      label: "专项销项",
      relative_path: "专项销项",
      path: "/合成/甲公司/专项销项",
      status: "present",
      kind: "custom",
      role: "issued_invoice_dir",
      role_label: "开具发票",
      location: "inside_root",
    },
  ],
  missing_subdir_count: 0,
  taxpayer_periods: [],
  current_taxpayer_type: null,
  current_taxpayer_label: "未设置",
  monitored: false,
  monitored_subdir_key: null,
};

const respond = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const list = (companies: Company[] = [COMPANY]) => ({
  ok: true,
  revision: 5,
  companies,
  monitored_company_id: null,
  target_id: "t1",
  watch_dir: "/合成监控",
  standard_subdirs: standards,
});

function setupPinia(companies: Company[] = [COMPANY]) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useCompaniesStore().list = list(companies);
  return { plugins: [pinia] };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("Phase 1 workspace CRUD & deep directory search", () => {
  it("supports non-destructive unregister and confirmed native recycle-bin trash in CompanyDeleteModal", async () => {
    const calls: { url: string; method: string; body?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith("/trash-preview")) {
        return respond({
          ok: true,
          company_id: COMPANY.id,
          company_name: COMPANY.name,
          revision: 5,
          path: COMPANY.root_path,
          can_trash: true,
          blocked_reason: "",
          file_count: 12,
          dir_count: 6,
          total_bytes: 20480,
          truncated: false,
          external_folders: [{ key: "dir_ext", label: "外部资料", path: "/外部/资料" }],
          plan_hash: "h".repeat(64),
        });
      }
      if (url.endsWith("/trash")) {
        return respond({ ok: true, deleted: COMPANY.id, trashed_path: COMPANY.root_path, external_folders_untouched: [], revision: 6 });
      }
      if (init.method === "DELETE") {
        return respond({ ok: true, deleted: COMPANY.id, revision: 6, files_touched: 0 });
      }
      return respond(list([]));
    }));

    const wrapper = mount(CompanyDeleteModal, { props: { company: COMPANY }, attachTo: document.body, global: setupPinia() });
    await flushPromises();
    const dialog1 = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    await dialog1.findAll("button").find((b) => b.text().includes("确认仅从清单移除"))!.trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.method === "DELETE" && c.url.includes("/api/v1/companies/co_1?revision=5"))).toBe(true);
    expect(wrapper.emitted("done")?.[0]?.[0]).toEqual({ companyId: COMPANY.id, trashed: false });
    wrapper.unmount();

    const wrapper2 = mount(CompanyDeleteModal, { props: { company: COMPANY }, attachTo: document.body, global: setupPinia() });
    await flushPromises();
    const dialog2 = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    await dialog2.get('input[type="radio"][value="trash"]').setValue(true);
    await flushPromises();
    expect(dialog2.text()).toContain("12");
    expect(dialog2.text()).toContain("外部资料");
    const confirmBtn = () => dialog2.findAll("button").find((b) => b.text().includes("确认移入回收站"))!;
    expect((confirmBtn().element as HTMLButtonElement).disabled).toBe(true);
    await dialog2.get('input[type="checkbox"]').setValue(true);
    expect((confirmBtn().element as HTMLButtonElement).disabled).toBe(false);
    await confirmBtn().trigger("click");
    await flushPromises();
    const trashCall = calls.find((c) => c.url.endsWith("/trash"));
    expect(trashCall?.body).toMatchObject({ plan_hash: "h".repeat(64), confirm: true, revision: 5 });
    expect(wrapper2.emitted("done")?.[0]?.[0]).toEqual({ companyId: COMPANY.id, trashed: true });
    wrapper2.unmount();
  });

  it("relocates root_dir or atomically renames company root folder in CompanySettings", async () => {
    const patchBodies: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      if (init.method === "PATCH") {
        patchBodies.push(JSON.parse(String(init.body)));
        return respond({ ok: true, revision: 6, company: COMPANY });
      }
      return respond(list([COMPANY]));
    }));

    const wrapper = mount(CompanySettings, { props: { company: COMPANY }, global: setupPinia() });
    await wrapper.get('[aria-label="公司资料夹路径"]').setValue("/合成/已迁移甲公司");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(patchBodies[0]).toMatchObject({ root_dir: "/合成/已迁移甲公司", revision: 5 });
    expect(patchBodies[0]).not.toHaveProperty("rename_root_on_disk");

    // Reset back and test disk rename checkbox.
    await wrapper.get('[aria-label="公司资料夹路径"]').setValue(COMPANY.root_path);
    await wrapper.get('input[type="checkbox"]').setValue(true);
    await wrapper.get('[aria-label="新的公司文件夹名"]').setValue("改名甲公司");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(patchBodies[1]).toMatchObject({ rename_root_on_disk: true, new_root_name: "改名甲公司", revision: 5 });
    expect(patchBodies[1]).not.toHaveProperty("root_dir");
    wrapper.unmount();
  });

  it("submits selected standard subset + custom folders on new workspace and extra folders on existing import", async () => {
    vi.useFakeTimers();
    const calls: { url: string; body?: Record<string, unknown> }[] = [];
    const job: CompanySetupJob = {
      ok: true,
      job_id: "b".repeat(32),
      state: "prepared",
      plan_hash: "p1",
      name: "新精简",
      root_path: "/父/新精简",
      items: [
        { key: "cost_invoice_dir", label: "成本发票", relative_path: "成本发票" },
        { key: "custom_0", label: "专项", relative_path: "专项", kind: "custom", role: "general" },
      ],
      created: [],
      in_progress: "",
      message: "",
      company: null,
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      const body = init.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, body });
      if (url.endsWith("/setup-jobs")) return respond(job);
      if (url.endsWith("/detect")) {
        return respond({
          root_status: "present",
          plan_hash: "det1",
          subdirs: standards.map((item) => ({ ...item, relative_path: item.label, path: `/旧/${item.label}`, status: "present", file_count: 0, suggested_action: "keep" })),
          extra_folders: [{ relative_path: "历史报销", path: "/旧/历史报销", label: "历史报销", suggested_role: "expense_reimbursement_dir", file_count: 3 }],
        });
      }
      if (url === "/api/v1/companies" && init.method === "POST") return respond({ ok: true, revision: 6, company: COMPANY });
      return respond(list([COMPANY]));
    }));

    // 1. Existing folder mode with extra_folders checkbox
    const w1 = mount(CompanyCreateForm, { global: setupPinia([]) });
    await w1.get('[aria-label="公司资料夹"]').setValue("/旧");
    await w1.get('[aria-label="公司名称"]').setValue("老公司");
    await w1.get('input[value="later"]').setValue(true);
    await vi.advanceTimersByTimeAsync(310);
    await flushPromises();
    expect(w1.text()).toContain("历史报销");
    await w1.get('[aria-label="一并导入 历史报销"]').setValue(true);
    await w1.get("form").trigger("submit");
    await flushPromises();
    const createCall = calls.find((c) => c.url === "/api/v1/companies" && c.body?.plan_hash === "det1");
    expect(createCall?.body?.import_extra_folders).toEqual([
      { relative_path: "历史报销", label: "历史报销", role: "expense_reimbursement_dir" },
    ]);
    w1.unmount();

    // 2. New workspace mode with subset of standard folders + custom folder
    const w2 = mount(CompanyCreateForm, { global: setupPinia([]) });
    await w2.findAll("button").find((b) => b.text() === "新建工作区")!.trigger("click");
    await w2.get('[aria-label="上级文件夹"]').setValue("/父");
    await w2.get('[aria-label="公司名称"]').setValue("新精简");
    await w2.get('input[value="later"]').setValue(true);
    await w2.get('[aria-label="创建 银行流水"]').setValue(false);
    await w2.findAll("button").find((b) => b.text().includes("添加自定义子目录"))!.trigger("click");
    await w2.get('[aria-label="自定义目录名称"]').setValue("专项");
    await w2.get("form").trigger("submit");
    await flushPromises();
    const setupCall = calls.find((c) => c.url.endsWith("/setup-jobs"));
    expect(setupCall?.body?.selected_standard_keys).not.toContain("bank_flow_dir");
    expect(setupCall?.body?.custom_folders).toEqual([{ label: "专项", relative_path: "专项", role: "general" }]);
    w2.unmount();
  });

  it("uses effectiveFolderRole for custom issued folder and sends workspace multi-token, advanced filters, amount sort and reset", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      if (url.includes("/invoices?")) {
        return respond({
          ok: true,
          count: 1,
          read_only: false,
          directory: { ...COMPANY.subdirs[6], target_id: "t_custom", active: true, read_only: false, projection: { summary_exists: true } },
          snapshot: { provisional: false, revision: "r1" },
          stats: {
            all: { total: 1, recognized: 1, needs_review: 0, duplicates: 0, total_amount: "1130.00", total_amount_valid_count: 1 },
            filtered: { total: 1, recognized: 1, needs_review: 0, duplicates: 0, total_amount: "1130.00", total_amount_valid_count: 1 },
          },
          filter_options: {
            projects: ["桥梁项目"],
            tax_rates: ["13%"],
            invoice_types: ["增值税专用发票"],
            business_types: ["标准电子发票"],
            has_unassigned_project: false,
            has_missing_tax_rate: false,
            has_duplicates: true,
          },
          items: [
            {
              invoice_key: "0",
              source_path: "/合成/甲公司/专项销项/a.pdf",
              source_file: "a.pdf",
              file_format: "PDF",
              invoice_type: "增值税专用发票",
              business_type: "标准电子发票",
              invoice_number: "20001",
              invoice_date: "2026-06-01",
              seller: "合成甲公司",
              buyer: "华星客户",
              amount: "1130.00",
              tax_rate: "0.13",
              project: "桥梁项目",
              status: "已识别",
            },
          ],
        });
      }
      return respond({ revision: 0, tags: [] });
    }));

    const wrapper = mount(DirectoryInvoices, {
      props: { company: COMPANY, dirKey: "dir_1234567890ab" },
      global: setupPinia(),
    });
    await flushPromises();

    // Custom issued_invoice_dir role must enable project column and buyer placeholder.
    expect((wrapper.get('[aria-label="关键字"]').element as HTMLInputElement).placeholder).toContain("购买方");
    expect(wrapper.text()).toContain("桥梁项目");

    // Enter triggers immediate workspace multi-token query.
    await wrapper.get('[aria-label="关键字"]').setValue("华星 13%");
    await wrapper.get('[aria-label="关键字"]').trigger("keydown.enter");
    await flushPromises();
    expect(urls.at(-1)).toContain("search_scope=workspace");
    expect(urls.at(-1)).toContain(encodeURIComponent("华星 13%"));

    // Expand advanced filters and set date_from, amount_min, tax_rate, project, duplicate status.
    await wrapper.findAll("button").find((b) => b.text().includes("高级筛选"))!.trigger("click");
    await wrapper.get('[aria-label="开票日期起"]').setValue("2026-06-01");
    await wrapper.get('[aria-label="最小金额"]').setValue("1000");
    await wrapper.get('[aria-label="最小金额"]').trigger("change");
    await wrapper.get('[aria-label="税率筛选"]').setValue("13%");
    await wrapper.get('[aria-label="按项目筛选"]').setValue("桥梁项目");
    await wrapper.get('[aria-label="状态"]').setValue("重复发票");
    await wrapper.get('[aria-label="按开票金额倒序排序"]').trigger("click");
    await flushPromises();

    const last = urls.at(-1)!;
    expect(last).toContain("date_from=2026-06-01");
    expect(last).toContain("amount_min=1000");
    expect(last).toContain("tax_rate=13%25");
    expect(last).toContain(`project=${encodeURIComponent("桥梁项目")}`);
    expect(last).toContain(`status=${encodeURIComponent("重复发票")}`);
    expect(last).toContain("sort_by=amount&sort_dir=desc");

    // Reset clears all filters and sorting.
    await wrapper.findAll("button").find((b) => b.text() === "重置筛选")!.trigger("click");
    await flushPromises();
    const afterReset = urls.at(-1)!;
    expect(afterReset).not.toContain("keyword=");
    expect(afterReset).not.toContain("amount_min=");
    expect(afterReset).not.toContain("sort_by=");
    wrapper.unmount();
  });
});
