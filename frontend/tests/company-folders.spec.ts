import { DOMWrapper, flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import App from "../src/App.vue";
import CompanyFolderCreateModal from "../src/components/CompanyFolderCreateModal.vue";
import CompanyFolderDeleteModal from "../src/components/CompanyFolderDeleteModal.vue";
import CompanyFolderEditModal from "../src/components/CompanyFolderEditModal.vue";
import CompanySettings from "../src/components/CompanySettings.vue";
import DirectoryPanel from "../src/components/DirectoryPanel.vue";
import { createAppRouter } from "../src/router";
import { useWorkspaceStore } from "../src/stores/workspace";
import type { Company, CompanyDirectory, CompanySubdir } from "../src/api/types";

const FOLDER_ROLES = [
  { key: "cost_invoice_dir", label: "成本发票", short_tag: "进项", description: "按进项/成本发票处理。" },
  { key: "issued_invoice_dir", label: "开具发票", short_tag: "销项", description: "按销项/开具发票处理。" },
  { key: "expense_reimbursement_dir", label: "费用报销", short_tag: "报销", description: "按费用报销发票处理。" },
  { key: "bank_flow_dir", label: "银行流水", short_tag: "流水", description: "按银行流水处理。" },
  { key: "input_deduction_dir", label: "进项抵扣", short_tag: "抵扣", description: "按进项抵扣处理。" },
  { key: "payroll_social_dir", label: "工资社保", short_tag: "工资", description: "按工资社保资料处理。" },
  { key: "general", label: "普通资料（未指定）", short_tag: "资料", description: "通用文件夹。" },
];

const SUBDIRS: CompanySubdir[] = [
  { key: "cost_invoice_dir", label: "成本发票", default_label: "成本发票", kind: "standard", role: "cost_invoice_dir", role_label: "成本发票", location: "inside_root", hidden: false, can_promote_to_role: false, relative_path: "成本发票", path: "/合成/甲/成本发票", status: "present" },
  { key: "issued_invoice_dir", label: "开具发票", default_label: "开具发票", kind: "standard", role: "issued_invoice_dir", role_label: "开具发票", location: "inside_root", hidden: false, can_promote_to_role: false, relative_path: "开具发票", path: "/合成/甲/开具发票", status: "present" },
  { key: "expense_reimbursement_dir", label: "费用报销", default_label: "费用报销", kind: "standard", role: "expense_reimbursement_dir", role_label: "费用报销", location: "inside_root", hidden: true, can_promote_to_role: false, relative_path: "费用报销", path: "/合成/甲/费用报销", status: "missing" },
  { key: "cf_cost_01", label: "2026补充进项", default_label: "2026补充进项", kind: "custom", role: "cost_invoice_dir", role_label: "成本发票", location: "inside_root", hidden: false, can_promote_to_role: true, relative_path: "补充进项", path: "/合成/甲/补充进项", status: "present" },
  { key: "cf_bank_ext", label: "外部招行流水", default_label: "外部招行流水", kind: "custom", role: "bank_flow_dir", role_label: "银行流水", location: "external", hidden: false, can_promote_to_role: false, relative_path: "/外部归档/招行流水", path: "/外部归档/招行流水", status: "present" },
  { key: "cf_pay_01", label: "外包社保", default_label: "外包社保", kind: "custom", role: "payroll_social_dir", role_label: "工资社保", location: "inside_root", hidden: false, can_promote_to_role: true, relative_path: "外包社保", path: "/合成/甲/外包社保", status: "present" },
];

const COMPANY: Company = {
  id: "co_1",
  name: "甲公司",
  root_dir: "/合成/甲",
  root_path: "/合成/甲",
  root_status: "present",
  subdirs: SUBDIRS,
  missing_subdir_count: 0,
  hidden_subdir_count: 1,
  taxpayer_periods: [],
  current_taxpayer_type: null,
  current_taxpayer_label: "未设置",
  monitored: true,
  monitored_subdir_key: "cost_invoice_dir",
};

const DIRECTORIES: CompanyDirectory[] = SUBDIRS.map((sub, idx) => ({
  ...sub,
  target_id: `t_${idx}`,
  active: sub.key === "cost_invoice_dir",
  read_only: sub.key !== "cost_invoice_dir",
  projection: { summary_exists: true, summary_updated_at: "2026-11-25 10:00:00", cost_detail_exists: false, cost_detail_updated_at: "" },
  freshness: { state: sub.key === "cost_invoice_dir" ? "monitored" : "fresh", message: "" },
}));

type Handler = (url: string, init: RequestInit) => [number, unknown] | undefined;
let calls: { url: string; method: string; body: unknown }[] = [];

function stubBackend(handler: Handler = () => undefined) {
  calls = [];
  let revision = 5;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({ url, method, body: init.body ? JSON.parse(String(init.body)) : undefined });
      const custom = handler(url, init);
      if (custom) {
        const [status, body] = custom;
        if (method !== "GET" && status === 200) revision += 1;
        return new Response(JSON.stringify(body), { status });
      }
      if (url.endsWith("/health")) return new Response(JSON.stringify({ ok: true, product_version: "1.0.0", watch_dir: "/合成/甲/成本发票", target_id: "t_0" }), { status: 200 });
      if (url.endsWith("/settings")) return new Response(JSON.stringify({ ok: true, watch_dir: "/合成/甲/成本发票", active_target_id: "t_0" }), { status: 200 });
      if (url === "/api/v1/companies" && method === "GET") {
        return new Response(JSON.stringify({ ok: true, revision, companies: [COMPANY], monitored_company_id: "co_1", target_id: "t_0", watch_dir: "/合成/甲/成本发票", folder_roles: FOLDER_ROLES }), { status: 200 });
      }
      if (url.endsWith("/directories")) return new Response(JSON.stringify({ ok: true, revision, company: COMPANY, directories: DIRECTORIES }), { status: 200 });
      if (url.includes("/projects?")) return new Response(JSON.stringify({ ok: true, projects: [] }), { status: 200 });
      if (url.includes("/ledger")) {
        const z = { count: 0, pretax: "0.00", tax: "0.00", total: "0.00" };
        return new Response(JSON.stringify({ ok: true, basis_label: "票面口径", granularity: "month", periods: [], totals: { input: z, output: z, face_difference_pretax: "0.00", face_difference_tax: "0.00" }, undated: { input: z, output: z }, excluded: [], merged_copies: { input: 0, output: 0 }, out_of_range: { input: 0, output: 0 }, warnings: [], checks: [], checks_ok: true, sources: { input: DIRECTORIES[0], output: DIRECTORIES[1] } }), { status: 200 });
      }
      if (url.endsWith("/invoice-tags")) return new Response(JSON.stringify({ ok: true, revision: 1, tags: [], invoices: {} }), { status: 200 });
      if (url.includes("/invoices?")) return new Response(JSON.stringify({ ok: true, count: 0, page: 1, page_size: 50, read_only: true, directory: DIRECTORIES[0], items: [] }), { status: 200 });
      if (url.includes("/period-folders")) return new Response(JSON.stringify({ ok: true, folders: [], items: [], mismatched: 0 }), { status: 200 });
      if (url.includes("/bank-layouts")) return new Response(JSON.stringify({ ok: true, revision: 1, layouts: [], files: [], fields: [] }), { status: 200 });
      if (url.includes("/payroll")) {
        return new Response(JSON.stringify({
          ok: true,
          months: [
            { month: "2026-10", total: "3200.50", source: "社保2026-10.xlsx", checks_ok: true, rows: [{ checks: [{ code: "total", ok: true, message: "ok" }] }] },
            { month: "2026-11", total: "150.00", source: "社保2026-11.xlsx", checks_ok: false, rows: [{ checks: [{ code: "total", ok: false, message: "养老保险：单位 100.00 + 个人 50.00 = 合计 200.00" }] }] },
          ],
          files: [{ file: "社保2026-10.xlsx", status: "parsed" }, { file: "杂项.png", status: "skipped", message: "图片需要 OCR" }],
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: `unexpected ${method} ${url}` }), { status: 404 });
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

describe("company custom folders & role dispatch", () => {
  it("supports create preview -> confirm, discovered/external import, and restoring hidden defaults", async () => {
    stubBackend((url, init) => {
      if (url.endsWith("/folders/discover")) {
        return [200, {
          ok: true,
          company_id: "co_1",
          candidates: [{ label: "历史专项", relative_path: "历史专项", path: "/合成/甲/历史专项", suggested_role: "expense_reimbursement_dir", suggested_role_label: "费用报销" }],
          hidden_standard_subdirs: [SUBDIRS[2]],
          roles: FOLDER_ROLES,
        }];
      }
      if (url.endsWith("/folders/create/preview")) {
        const body = JSON.parse(String(init.body));
        return [200, { ok: true, company_id: "co_1", label: body.label, relative_path: body.relative_path, path: `/合成/甲/${body.relative_path}`, role: body.role, role_label: "成本发票", action: "create", reason: "", plan_hash: "ph_create_1" }];
      }
      if (url.endsWith("/folders/create")) {
        return [200, { ok: true, revision: 6, company: COMPANY, folder_id: "cf_new_1", created: true }];
      }
      if (url === "/api/v1/companies/pick-directory") {
        return [200, { ok: true, selected: true, path: "/外部/临时测试发票" }];
      }
      if (url.endsWith("/folders/import")) {
        return [200, { ok: true, revision: 7, company: COMPANY, folder_id: "cf_ext_1", location: "external" }];
      }
      if (url.endsWith("/folders/expense_reimbursement_dir/restore")) {
        return [200, { ok: true, revision: 8, company: COMPANY, restored: true }];
      }
      return undefined;
    });

    setActivePinia(createPinia());
    const wrapper = mount(CompanyFolderCreateModal, {
      props: { company: COMPANY, initialMode: "create" },
      attachTo: document.body,
    });
    await flushPromises();

    const dialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    // 1. Create empty folder: preview -> confirm with plan_hash
    await dialog.get('input[placeholder*="临时验收副本"]').setValue("临时验收");
    await dialog.findAll("button").find((b) => b.text() === "预览创建")!.trigger("click");
    await flushPromises();
    expect(dialog.get('[aria-label="新建预览"]').text()).toContain("/合成/甲/临时验收");
    expect(calls.some((c) => c.url.endsWith("/folders/create"))).toBe(false);

    await dialog.findAll("button").find((b) => b.text() === "确认创建空文件夹")!.trigger("click");
    await flushPromises();
    const createCall = calls.find((c) => c.url.endsWith("/folders/create"))!;
    expect(createCall.body).toMatchObject({ label: "临时验收", relative_path: "临时验收", role: "cost_invoice_dir", plan_hash: "ph_create_1", confirm: true });
    expect(wrapper.emitted("done")?.[0]).toEqual(["cf_new_1"]);

    // 2. Import tab: click discovered candidate chip, then test native picker for external path
    await dialog.findAll('[role="tab"]').find((b) => b.text().includes("导入已有文件夹"))!.trigger("click");
    await flushPromises();
    const chip = dialog.findAll(".folder-chip")[0]!;
    expect(chip.text()).toContain("历史专项");
    await chip.trigger("click");
    expect((dialog.get('input[placeholder*="选择文件夹"]').element as HTMLInputElement).value).toBe("/合成/甲/历史专项");

    await dialog.findAll("button").find((b) => b.text() === "选择文件夹…")!.trigger("click");
    await flushPromises();
    expect((dialog.get('input[placeholder*="选择文件夹"]').element as HTMLInputElement).value).toBe("/外部/临时测试发票");
    await dialog.findAll("button").find((b) => b.text() === "确认导入")!.trigger("click");
    await flushPromises();
    const importCall = calls.find((c) => c.url.endsWith("/folders/import"))!;
    expect(importCall.body).toMatchObject({ path: "/外部/临时测试发票", label: "临时测试发票", role: "expense_reimbursement_dir" });

    // 3. Restore hidden default tab
    await dialog.findAll('[role="tab"]').find((b) => b.text().includes("恢复隐藏默认目录"))!.trigger("click");
    await flushPromises();
    await dialog.findAll("button").find((b) => b.text() === "恢复显示")!.trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.url.endsWith("/folders/expense_reimbursement_dir/restore") && c.method === "POST")).toBe(true);
    wrapper.unmount();
  });

  it("guards disk rename when monitored and supports label/role edit, disk rename sync, and promote", async () => {
    stubBackend((url) => {
      if (url.includes("/update")) return [200, { ok: true, revision: 6, company: COMPANY, renamed_disk: true }];
      if (url.includes("/promote")) return [200, { ok: true, revision: 7, company: COMPANY, promoted_to: "cost_invoice_dir", preserved_previous_id: "cf_prev" }];
      return undefined;
    });

    setActivePinia(createPinia());
    // Monitored standard folder: disk rename checkbox must be disabled
    const monitoredWrapper = mount(CompanyFolderEditModal, {
      props: { company: COMPANY, subdir: SUBDIRS[0]! },
      attachTo: document.body,
    });
    await flushPromises();
    const monitoredDialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    const monitoredDiskCheck = monitoredDialog.get('input[type="checkbox"]').element as HTMLInputElement;
    expect(monitoredDiskCheck.disabled).toBe(true);
    expect(monitoredDialog.text()).toContain("当前正在监控此文件夹");
    monitoredWrapper.unmount();
    document.body.innerHTML = "";

    // Non-monitored inside_root custom folder: edit label + check disk rename (auto-syncs!) + promote
    const customWrapper = mount(CompanyFolderEditModal, {
      props: { company: COMPANY, subdir: SUBDIRS[3]! },
      attachTo: document.body,
    });
    await flushPromises();
    const dialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    await dialog.get('input[maxlength="80"]').setValue("2026Q4补充");
    await dialog.get('input[type="checkbox"]').setValue(true);
    const diskInput = dialog.get('input.mono').element as HTMLInputElement;
    expect(diskInput.value).toBe("2026Q4补充");
    await dialog.get("form").trigger("submit");
    await flushPromises();
    const patchCall = calls.find((c) => c.method === "POST" && c.url.endsWith("/folders/cf_cost_01/update"))!;
    expect(patchCall.body).toMatchObject({ label: "2026Q4补充", role: "cost_invoice_dir", rename_disk: true, new_relative_path: "2026Q4补充" });

    // Promote flow requires explicit second confirmation
    await dialog.findAll("button").find((b) => b.text().includes("设为主「成本发票」目录"))!.trigger("click");
    expect(dialog.find('[role="alertdialog"][aria-label="确认切换主目录"]').exists()).toBe(true);
    await dialog.findAll("button").find((b) => b.text() === "确认切换")!.trigger("click");
    await flushPromises();
    const promoteCall = calls.find((c) => c.method === "POST" && c.url.endsWith("/folders/cf_cost_01/promote"))!;
    expect(promoteCall.body).toMatchObject({ target_role: "cost_invoice_dir", keep_previous_as_custom: true });
    expect(customWrapper.emitted("done")?.at(-1)).toEqual(["cost_invoice_dir"]);
    customWrapper.unmount();
  });

  it("defaults delete modal to non-destructive unregister and requires preview + checkbox for OS trash", async () => {
    stubBackend((url) => {
      if (url.endsWith("/trash/preview")) {
        return [200, {
          ok: true, company_id: "co_1", key: "cf_bank_ext", label: "外部招行流水", path: "/外部归档/招行流水",
          is_external: true, file_count: 3, dir_count: 1, total_bytes: 2048, truncated: false,
          can_trash: true, blocked_reason: "", plan_hash: "ph_trash_1",
        }];
      }
      if (url.endsWith("/folders/cf_bank_ext/remove")) return [200, { ok: true, revision: 6, company: COMPANY, files_touched: 0 }];
      if (url.endsWith("/folders/cf_bank_ext/trash")) return [200, { ok: true, revision: 7, company: COMPANY, trashed: true, unregistered: true }];
      return undefined;
    });

    setActivePinia(createPinia());
    const wrapper = mount(CompanyFolderDeleteModal, {
      props: { company: COMPANY, subdir: SUBDIRS[4]! },
      attachTo: document.body,
    });
    await flushPromises();
    const dialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    // Default unregister mode never hits /trash/preview
    expect(calls.some((c) => c.url.includes("/trash"))).toBe(false);
    await dialog.findAll("button").find((b) => b.text() === "确认仅移除登记")!.trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.url.endsWith("/folders/cf_bank_ext/remove") && c.method === "POST")).toBe(true);

    // Switch to OS trash mode: loads preview, shows external warning, gates confirm button on checkbox
    await dialog.get('input[type="radio"][value="trash"]').setValue(true);
    await flushPromises();
    expect(dialog.text()).toContain("3 个文件");
    expect(dialog.text()).toContain("外部导入文件夹");
    const confirmBtn = () => dialog.findAll("button").find((b) => b.text() === "确认移入系统回收站")!;
    expect((confirmBtn().element as HTMLButtonElement).disabled).toBe(true);
    const checkboxes = dialog.findAll('input[type="checkbox"]');
    await checkboxes[1]!.setValue(true);
    expect((confirmBtn().element as HTMLButtonElement).disabled).toBe(false);
    await confirmBtn().trigger("click");
    await flushPromises();
    const trashCall = calls.find((c) => c.url.endsWith("/folders/cf_bank_ext/trash"))!;
    expect(trashCall.body).toMatchObject({ plan_hash: "ph_trash_1", confirm: true, also_unregister: true });
    wrapper.unmount();
  });

  it("filters hidden default dirs in sidebar and dispatches role-specific panels for custom folders", async () => {
    stubBackend();
    setActivePinia(createPinia());
    const router = createAppRouter(createMemoryHistory());
    await router.push("/companies");
    const app = mount(App, { global: { plugins: [router] }, attachTo: document.body });
    await flushPromises();

    // Expand company in sidebar and verify hidden expense_reimbursement_dir is not listed, while custom dirs show role tags
    expect(app.text()).toContain("已隐藏默认目录（1）");
    expect(app.get("aside.ws-sidebar").text()).toContain("资料 5/5");
    await app.get(".ws-row--company .ws-toggle").trigger("click");
    await flushPromises();
    const expandedSidebarText = app.get("aside.ws-sidebar").text();
    expect(expandedSidebarText).not.toContain("费用报销");
    expect(expandedSidebarText).toContain("2026补充进项");
    expect(expandedSidebarText).toContain("外部招行流水");
    expect(expandedSidebarText).toContain("外包社保");
    app.unmount();
    document.body.innerHTML = "";

    // DirectoryPanel with custom bank_flow_dir passes dir_key to /bank-layouts and /period-folders
    const bankPanel = mount(DirectoryPanel, { props: { company: COMPANY, dirKey: "cf_bank_ext" } });
    await flushPromises();
    expect(bankPanel.text()).toContain("外部导入 · 银行流水");
    expect(calls.some((c) => c.url.includes("/period-folders?key=cf_bank_ext"))).toBe(true);
    expect(calls.some((c) => c.url.includes("/bank-layouts?files=1&dir_key=cf_bank_ext"))).toBe(true);
    bankPanel.unmount();

    // DirectoryPanel with custom payroll_social_dir loads read-only payroll preview with dir_key
    // and surfaces backend check failures prominently (never hiding checks_ok: false).
    calls = [];
    const payrollPanel = mount(DirectoryPanel, { props: { company: COMPANY, dirKey: "cf_pay_01" } });
    await flushPromises();
    expect(calls.some((c) => c.url.includes("/payroll?dir_key=cf_pay_01"))).toBe(true);
    const preview = payrollPanel.get('[aria-label="自定义工资社保目录预览"]');
    expect(preview.text()).toContain("3200.50");
    expect(preview.find('[role="alert"]').text()).toContain("核对未通过");
    expect(preview.get("tr.row--danger").text()).toContain("养老保险：单位 100.00 + 个人 50.00 = 合计 200.00");
    expect(preview.text()).toContain("另有 1 个未识别文件");
    payrollPanel.unmount();
  });

  it("auto-closes DirectoryPanel edit modal after rename and closes tab/pin/compare on unregister", async () => {
    let renamed = false;
    let removed = false;
    stubBackend((url) => {
      if (url.endsWith("/folders/cf_cost_01/update")) {
        renamed = true;
        return [200, { ok: true, revision: 6, company: COMPANY, disk_renamed: true }];
      }
      if (url.endsWith("/folders/cf_cost_01/remove")) {
        removed = true;
        return [200, { ok: true, revision: 7, company: COMPANY, files_touched: 0 }];
      }
      if (url === "/api/v1/companies") {
        const subdirs = removed
          ? SUBDIRS.filter((s) => s.key !== "cf_cost_01")
          : SUBDIRS.map((s) => (renamed && s.key === "cf_cost_01" ? { ...s, label: "已改名", path: "/合成/甲/已改名", relative_path: "已改名", role: "bank_flow_dir" as const, role_label: "银行流水" } : s));
        return [200, { ok: true, revision: removed ? 7 : renamed ? 6 : 5, companies: [{ ...COMPANY, subdirs }], monitored_company_id: "co_1", target_id: "t_0", watch_dir: "/合成/甲/成本发票", folder_roles: FOLDER_ROLES }];
      }
      return undefined;
    });

    setActivePinia(createPinia());
    const workspace = useWorkspaceStore();
    const openedTab = workspace.open({ kind: "directory", companyId: "co_1", dirKey: "cf_cost_01" });
    workspace.open({ kind: "compare", companyId: "co_1", dirKey: "cf_cost_01", otherCompanyId: "co_1", otherDirKey: "issued_invoice_dir", relation: "input_output" });
    workspace.pins = ["dir:co_1:cf_cost_01"];
    workspace.compareBase = { companyId: "co_1", dirKey: "cf_cost_01" };

    const panel = mount(DirectoryPanel, { props: { company: COMPANY, dirKey: "cf_cost_01" }, attachTo: document.body });
    await flushPromises();
    await panel.findAll("button").find((b) => b.text() === "重命名 / 指向")!.trigger("click");
    await flushPromises();
    expect(document.body.querySelector('[role="dialog"]')).not.toBeNull();
    const editDialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    await editDialog.get('input[maxlength="80"]').setValue("已改名");
    await editDialog.get("form").trigger("submit");
    await flushPromises();
    // Modal must auto-close even when companySourceKey changes during save.
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();

    await panel.findAll("button").find((b) => b.text() === "移除 / 删除")!.trigger("click");
    await flushPromises();
    const delDialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    await delDialog.findAll("button").find((b) => b.text() === "确认仅移除登记")!.trigger("click");
    await flushPromises();
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    expect(workspace.tabs.some((t) => t.id === openedTab.id)).toBe(false);
    expect(workspace.tabs.some((t) => t.kind === "compare")).toBe(false);
    expect(workspace.pins).toEqual([]);
    expect(workspace.compareBase).toBeNull();
    panel.unmount();
  });

  it("syncs untouched CompanySettings mappings after a folder rename and blocks stale edited mapping overwrites", async () => {
    stubBackend((url, init) => {
      if (url === "/api/v1/companies/co_1" && init.method === "PATCH") {
        return [200, { ok: true, revision: 6, company: { ...COMPANY, name: "甲公司改名" } }];
      }
      return undefined;
    });
    setActivePinia(createPinia());
    const wrapper = mount(CompanySettings, { props: { company: COMPANY } });
    await flushPromises();

    // User only edits company name (leaves cost_invoice_dir untouched), while elsewhere
    // cost_invoice_dir was renamed on disk to "成本新名".
    await wrapper.get('input[maxlength="80"]').setValue("甲公司改名");
    const renamedCompany: Company = {
      ...COMPANY,
      subdirs: SUBDIRS.map((s) => (s.key === "cost_invoice_dir" ? { ...s, relative_path: "成本新名", path: "/合成/甲/成本新名" } : s)),
    };
    await wrapper.setProps({ company: renamedCompany });
    await flushPromises();

    // Untouched mapping auto-refreshes to "成本新名" while unsaved name draft stays intact!
    expect((wrapper.get('input[aria-label="成本发票 映射"]').element as HTMLInputElement).value).toBe("成本新名");
    expect((wrapper.get('input[maxlength="80"]').element as HTMLInputElement).value).toBe("甲公司改名");

    // Saving submits ONLY the name change and does NOT undo "成本新名" back to "成本发票".
    await wrapper.get('form[aria-label="公司设置"]').trigger("submit");
    await flushPromises();
    const patch = calls.find((c) => c.method === "PATCH" && c.url === "/api/v1/companies/co_1")!;
    expect(patch.body).toEqual({ name: "甲公司改名", taxpayer_periods: [], revision: 5 });

    // If the user DID edit cost_invoice_dir AND it then changes externally, preserve draft & block silent overwrite.
    calls = [];
    await wrapper.get('input[aria-label="成本发票 映射"]').setValue("手输路径");
    const promotedCompany: Company = {
      ...renamedCompany,
      subdirs: renamedCompany.subdirs.map((s) => (s.key === "cost_invoice_dir" ? { ...s, relative_path: "晋升成本", path: "/合成/甲/晋升成本" } : s)),
    };
    await wrapper.setProps({ company: promotedCompany });
    await flushPromises();
    expect((wrapper.get('input[aria-label="成本发票 映射"]').element as HTMLInputElement).value).toBe("手输路径");
    await wrapper.get('form[aria-label="公司设置"]').trigger("submit");
    await flushPromises();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    expect(wrapper.get('[role="alert"]').text()).toContain("已在别处重命名或切换");
    wrapper.unmount();
  });
});
