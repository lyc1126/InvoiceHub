import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import CompanyCreateForm from "../src/components/CompanyCreateForm.vue";
import CompanySettings from "../src/components/CompanySettings.vue";
import CompanyProjects from "../src/components/CompanyProjects.vue";
import DirectoryPanel from "../src/components/DirectoryPanel.vue";
import DirectoryInvoices from "../src/components/DirectoryInvoices.vue";
import { useCompaniesStore } from "../src/stores/companies";
import type { Company, CompanySetupJob } from "../src/api/types";

const standards = [
  ["cost_invoice_dir", "成本发票"], ["issued_invoice_dir", "开具发票"], ["bank_flow_dir", "银行流水"],
  ["input_deduction_dir", "进项抵扣"], ["payroll_social_dir", "工资社保"], ["expense_reimbursement_dir", "费用报销"],
].map(([key, label]) => ({ key: key!, label: label! }));
const COMPANY: Company = { id: "co_1", name: "合成公司", root_dir: "/合成/甲", root_path: "/合成/甲", root_status: "present",
  subdirs: standards.map((item) => ({ ...item, relative_path: item.label, path: `/合成/甲/${item.label}`, status: "present" })),
  missing_subdir_count: 0, taxpayer_periods: [], current_taxpayer_type: null, current_taxpayer_label: "未设置", monitored: false, monitored_subdir_key: null };
const JOB: CompanySetupJob = { ok: true, job_id: "a".repeat(32), state: "prepared", plan_hash: "h1", name: "合成新公司",
  root_path: "/合成父目录/合成新公司", items: standards.map((item) => ({ ...item, relative_path: item.label })), created: [], in_progress: "", message: "", company: null };
const respond = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const list = (companies: Company[] = []) => ({ ok: true, revision: 3, companies, monitored_company_id: null, target_id: "t1", watch_dir: "/合成监控", standard_subdirs: standards });
const changedCompany = () => ({ ...COMPANY, subdirs: COMPANY.subdirs.map((item, index) => index ? item : { ...item, relative_path: "新进项", path: "/合成/甲/新进项" }) });
const setup = () => {
  const pinia = createPinia();
  setActivePinia(pinia);
  useCompaniesStore().list = list();
  return { plugins: [pinia] };
};

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("company setup and mapping", () => {
  it("does not save a picker result, rejects duplicate clicks and preserves a manually edited draft", async () => {
    let finish!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { finish = resolve; });
    let cancel = false;
    const fetcher = vi.fn(async (_url: string) => cancel ? respond({ selected: false, path: "" }) : pending);
    vi.stubGlobal("fetch", fetcher);
    const wrapper = mount(CompanyCreateForm, { global: setup() });
    await wrapper.get('[aria-label="公司资料夹"]').setValue("/合成旧草稿");
    const picker = wrapper.findAll("button").find((button) => button.text() === "选择公司资料夹…")!;
    await picker.trigger("click");
    await picker.trigger("click");
    expect(fetcher).toHaveBeenCalledTimes(1);
    await wrapper.get('[aria-label="公司资料夹"]').setValue("/手工修改草稿");
    finish(respond({ selected: true, path: "/迟到选择" }));
    await flushPromises();
    expect((wrapper.get('[aria-label="公司资料夹"]').element as HTMLInputElement).value).toBe("/手工修改草稿");
    expect(wrapper.text()).toContain("未采用选择器的迟到结果");
    cancel = true;
    await wrapper.findAll("button").find((button) => button.text() === "选择公司资料夹…")!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("原路径草稿保留");
    expect(fetcher.mock.calls.every(([url]) => url === "/api/v1/companies/pick-directory")).toBe(true);
    wrapper.unmount();
  });

  it("previews a new workspace then reads a lost confirmation result instead of confirming twice", async () => {
    const calls: { url: string; body: unknown }[] = [];
    const completed: CompanySetupJob = { ...JOB, state: "completed", created: [".", ...standards.map((item) => item.label)], company: { ...COMPANY, id: "co_new", name: JOB.name } };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, body: init.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith("/confirm")) return respond({ detail: "synthetic lost response" }, 503);
      if (url.endsWith(`/setup-jobs/${JOB.job_id}`)) return respond(completed);
      if (url.endsWith("/setup-jobs")) return respond(JOB);
      return respond(list([completed.company!]));
    }));
    const wrapper = mount(CompanyCreateForm, { global: setup() });
    await wrapper.findAll("button").find((button) => button.text() === "新建工作区")!.trigger("click");
    await wrapper.get('[aria-label="公司名称"]').setValue(JOB.name);
    await wrapper.get('[aria-label="上级文件夹"]').setValue("/合成父目录");
    await wrapper.get('[aria-label="成本发票 子目录"]').setValue("财务/进项");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(calls).toHaveLength(1);
    expect(calls[0]!.body).toMatchObject({ revision: 3, name: JOB.name, folder_name: JOB.name, subdirs: { cost_invoice_dir: "财务/进项" }, taxpayer_periods: [] });
    expect(wrapper.get('[aria-label="新建工作区计划"]').text()).toContain(JOB.root_path);
    await wrapper.findAll("button").find((button) => button.text() === "确认创建并登记")!.trigger("click");
    await flushPromises();
    expect(calls.filter((call) => call.url.endsWith("/confirm"))).toHaveLength(1);
    expect(calls.some((call) => call.url.endsWith(`/setup-jobs/${JOB.job_id}`))).toBe(true);
    expect(wrapper.emitted("created")![0]![0]).toEqual(Object.fromEntries(standards.map((item) => [item.key, "created"])));
    expect(calls.some((call) => call.url.includes("/settings"))).toBe(false);
    wrapper.unmount();
  });

  it("keeps an interrupted creation query-only", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      calls.push(url);
      if (url.endsWith("/confirm")) return respond({ detail: "synthetic timeout" }, 503);
      return respond(url.endsWith("/setup-jobs") ? JOB : { ...JOB, state: "unknown", message: "创建结果待核对" });
    }));
    const wrapper = mount(CompanyCreateForm, { global: setup() });
    await wrapper.findAll("button").find((button) => button.text() === "新建工作区")!.trigger("click");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    await wrapper.findAll("button").find((button) => button.text() === "确认创建并登记")!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("创建结果待核对");
    await wrapper.findAll("button").find((button) => button.text() === "读取执行结果")!.trigger("click");
    await flushPromises();
    expect(calls.filter((url) => url.endsWith("/confirm"))).toHaveLength(1);
    expect(wrapper.emitted("created")).toBeUndefined();
    wrapper.unmount();
  });

  it("preserves mapping drafts on a company refresh and only sends changed references", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, body: init.body ? JSON.parse(String(init.body)) : undefined });
      return respond(init.method === "PATCH" ? { ok: true, revision: 4, company: changedCompany() } : list([changedCompany()]));
    }));
    const wrapper = mount(CompanySettings, { props: { company: COMPANY }, global: setup() });
    await wrapper.get('[aria-label="成本发票 映射"]').setValue("新进项");
    await wrapper.setProps({ company: { ...COMPANY, missing_subdir_count: 1 } });
    expect((wrapper.get('[aria-label="成本发票 映射"]').element as HTMLInputElement).value).toBe("新进项");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(calls.find((call) => call.body)!.body).toEqual({ name: COMPANY.name, taxpayer_periods: [], subdirs: { cost_invoice_dir: "新进项" }, revision: 3 });
    expect(calls.every((call) => !call.url.includes("/moves") && !call.url.includes("/settings"))).toBe(true);
    wrapper.unmount();
  });

  it("drops old invoice selections when the mapped source changes", async () => {
    let mapped = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/invoices?")) return respond({ count: 1, read_only: mapped, directory: { label: "成本发票", target_id: mapped ? "t2" : "t1", projection: { summary_exists: true } },
        snapshot: { provisional: false, revision: mapped ? "r2" : "r1" }, items: [{ invoice_key: "0", source_path: "/合成/a.xml", source_file: "a.xml", file_format: "XML", invoice_number: "11" }] });
      return respond({ revision: 0, tags: [] });
    }));
    const wrapper = mount(DirectoryInvoices, { props: { company: COMPANY, dirKey: "cost_invoice_dir" }, global: setup() });
    await flushPromises();
    await wrapper.get('[aria-label="勾选本页"]').setValue(true);
    expect(wrapper.find('[aria-label="已勾选发票"]').exists()).toBe(true);
    mapped = true;
    await wrapper.setProps({ company: changedCompany() });
    await flushPromises();
    expect(wrapper.find('[aria-label="已勾选发票"]').exists()).toBe(false);
    expect(wrapper.find('[aria-label="勾选本页"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps unsaved project assignments visible and blocks saving stale source results", async () => {
    const totals = { count: 0, pretax: "0.00", tax: "0.00", total: "0.00" };
    vi.stubGlobal("fetch", vi.fn(async () => respond({ basis_label: "票面口径", assignments_revision: 1, projects: [], project_names: [],
      unassigned_invoices: [{ direction: "input", invoice_number: "11", invoice_date: "2026-06-01", counterpart: "合成销售方", total: "113.00", project: "", source: "none", remark_projects: [], assignable: true, source_files: [] }],
      manual_invoices: [], warnings: [], checks: [], checks_ok: true, totals })));
    const wrapper = mount(CompanyProjects, { props: { company: COMPANY }, global: setup() });
    await flushPromises();
    await wrapper.get('[aria-label="11 项目"]').setValue("未保存项目");
    await wrapper.setProps({ company: changedCompany() });
    expect(wrapper.text()).toContain("未保存的项目归属已保留");
    expect((wrapper.get('[aria-label="11 项目"]').element as HTMLInputElement).value).toBe("未保存项目");
    expect(wrapper.get('form[aria-label="项目归属"] button.primary').attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });

  it("hides an old directory and switch confirmation while a new mapping loads", async () => {
    const directory = (path: string) => ({ key: "cost_invoice_dir", label: "成本发票", path, status: "present", active: false,
      freshness: { state: "current", message: "" }, projection: { summary_updated_at: "" } });
    let finish!: (value: Response) => void;
    let count = 0;
    vi.stubGlobal("fetch", vi.fn(async () => ++count === 1
      ? respond({ directories: [directory("/合成/甲/旧进项")] })
      : new Promise<Response>((resolve) => { finish = resolve; })));
    const wrapper = mount(DirectoryPanel, { props: { company: COMPANY, dirKey: "cost_invoice_dir" },
      global: { ...setup(), stubs: { DirectoryInvoices: true, WatchSwitchConfirm: true } } });
    await flushPromises();
    await wrapper.findAll("button").find((button) => button.text() === "设为监控目录")!.trigger("click");
    expect(wrapper.find("watch-switch-confirm-stub").exists()).toBe(true);
    await wrapper.setProps({ company: changedCompany() });
    expect(wrapper.text()).not.toContain("/合成/甲/旧进项");
    expect(wrapper.find("watch-switch-confirm-stub").exists()).toBe(false);
    expect(wrapper.findAll("button").some((button) => button.text() === "设为监控目录")).toBe(false);
    finish(respond({ directories: [directory("/合成/甲/新进项")] }));
    await flushPromises();
    expect(wrapper.text()).toContain("/合成/甲/新进项");
    wrapper.unmount();
  });
});
