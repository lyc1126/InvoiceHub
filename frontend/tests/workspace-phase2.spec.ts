import { DOMWrapper, flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import DirectoryInvoices from "../src/components/DirectoryInvoices.vue";
import DirectoryPanel from "../src/components/DirectoryPanel.vue";
import WorkspaceSearchModal from "../src/components/WorkspaceSearchModal.vue";
import WorkspaceSidebar from "../src/components/WorkspaceSidebar.vue";
import { createAppRouter } from "../src/router";
import { useCompaniesStore } from "../src/stores/companies";
import { useWorkspaceStore } from "../src/stores/workspace";
import type { Company, CompanyDirectory } from "../src/api/types";

const COMPANY_A: Company = {
  id: "co_a",
  name: "甲公司",
  root_dir: "/合成/甲",
  root_path: "/合成/甲",
  root_status: "present",
  subdirs: [
    { key: "cost_invoice_dir", label: "成本发票", default_label: "成本发票", kind: "standard", role: "cost_invoice_dir", role_label: "成本发票", location: "inside_root", hidden: false, can_promote_to_role: false, relative_path: "成本发票", path: "/合成/甲/成本发票", status: "present" },
    { key: "expense_reimbursement_dir", label: "费用报销", default_label: "费用报销", kind: "standard", role: "expense_reimbursement_dir", role_label: "费用报销", location: "inside_root", hidden: false, can_promote_to_role: false, relative_path: "费用报销", path: "/合成/甲/费用报销", status: "present" },
    { key: "cf_general", label: "合同归档", default_label: "合同归档", kind: "custom", role: "general", role_label: "普通资料", location: "inside_root", hidden: false, can_promote_to_role: false, relative_path: "合同归档", path: "/合成/甲/合同归档", status: "present" },
  ],
  missing_subdir_count: 0,
  hidden_subdir_count: 0,
  taxpayer_periods: [],
  current_taxpayer_type: "general",
  current_taxpayer_label: "一般纳税人",
  monitored: true,
  monitored_subdir_key: "cost_invoice_dir",
};

const COMPANY_B: Company = {
  id: "co_b",
  name: "乙公司",
  root_dir: "/合成/乙",
  root_path: "/合成/乙",
  root_status: "present",
  subdirs: [
    { key: "cost_invoice_dir", label: "成本发票", default_label: "成本发票", kind: "standard", role: "cost_invoice_dir", role_label: "成本发票", location: "inside_root", hidden: false, can_promote_to_role: false, relative_path: "成本发票", path: "/合成/乙/成本发票", status: "present" },
  ],
  missing_subdir_count: 0,
  hidden_subdir_count: 0,
  taxpayer_periods: [],
  current_taxpayer_type: "small_scale",
  current_taxpayer_label: "小规模纳税人",
  monitored: false,
  monitored_subdir_key: null,
};

const DIRS_A: CompanyDirectory[] = COMPANY_A.subdirs.map((sub, idx) => ({
  ...sub,
  target_id: `t_a_${idx}`,
  active: sub.key === "cost_invoice_dir",
  read_only: sub.key !== "cost_invoice_dir",
  projection: { summary_exists: true, summary_updated_at: "2026-11-26 10:00:00", cost_detail_exists: false, cost_detail_updated_at: "" },
  freshness: { state: sub.key === "cost_invoice_dir" ? "monitored" : "fresh", message: "" },
}));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

describe("Phase 2 WS-11 global search & sidebar collapsed project search", () => {
  it("runs cross-company search and locates clicked invoice in target DirectoryInvoices", async () => {
    const requests: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        requests.push(url);
        if (url === "/api/v1/companies") {
          return new Response(JSON.stringify({ ok: true, revision: 2, companies: [COMPANY_A, COMPANY_B], monitored_company_id: "co_a", target_id: "t_a_0", watch_dir: "/合成/甲/成本发票", folder_roles: [] }), { status: 200 });
        }
        if (url.startsWith("/api/v1/workspace/search")) {
          return new Response(JSON.stringify({
            ok: true,
            query: { q: "地铁" },
            total_matches: 1,
            truncated: false,
            stats: { companies_scanned: 2, directories_scanned: 2, unbuilt_directories: 1, invoices_scanned: 15 },
            directories: [{ company_id: "co_a", company_name: "甲公司", dir_key: "cf_general", dir_label: "合同归档", role: "general", role_label: "普通资料", kind: "custom", location: "inside_root", status: "present", monitored: false }],
            projects: [{ company_id: "co_b", company_name: "乙公司", project: "地铁二期" }],
            items: [{
              invoice_key: "0",
              source_file: "b_cost.xml",
              source_path: "/合成/乙/成本发票/b_cost.xml",
              file_type: "xml",
              invoice_number: "26000009",
              invoice_date: "2026-11-18",
              seller: "北方机电",
              buyer: "乙公司",
              amount: "3450.00",
              tax_rate: "13%",
              status: "已识别",
              project: "地铁二期",
              company_id: "co_b",
              company_name: "乙公司",
              dir_key: "cost_invoice_dir",
              dir_label: "成本发票",
              dir_role: "cost_invoice_dir",
              dir_role_label: "成本发票",
              dir_kind: "standard",
              dir_location: "inside_root",
              monitored: false,
              read_only: true,
            }],
          }), { status: 200 });
        }
        if (url === "/api/v1/invoice-tags") {
          return new Response(JSON.stringify({ ok: true, revision: 1, tags: [] }), { status: 200 });
        }
        if (url.includes("/directories/cost_invoice_dir/invoices")) {
          return new Response(JSON.stringify({
            ok: true,
            count: 1,
            page: 1,
            page_size: 100,
            read_only: true,
            directory: { ...DIRS_A[0], active: false, read_only: true },
            items: [],
          }), { status: 200 });
        }
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }),
    );

    setActivePinia(createPinia());
    const workspace = useWorkspaceStore();
    const modal = mount(WorkspaceSearchModal, { attachTo: document.body });
    await flushPromises();

    const dialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    expect(dialog.text()).toContain("北方机电");
    expect(dialog.text()).toContain("地铁二期");
    expect(dialog.text()).toContain("另有 1 个目录尚未读取数据");

    await dialog.get("tbody tr.ws-gsearch__row").trigger("click");
    await flushPromises();

    expect(workspace.active?.kind).toBe("directory");
    expect(workspace.active?.companyId).toBe("co_b");
    expect(workspace.pendingLocate?.query).toBe("26000009");

    // Mounting DirectoryInvoices for co_b/cost_invoice_dir consumes pendingLocate and filters by 26000009
    const dirInv = mount(DirectoryInvoices, { props: { company: COMPANY_B, dirKey: "cost_invoice_dir" } });
    await flushPromises();
    expect(workspace.pendingLocate).toBeNull();
    expect(requests.some((u) => u.includes("/co_b/directories/cost_invoice_dir/invoices") && u.includes("keyword=26000009"))).toBe(true);

    dirInv.unmount();
    modal.unmount();
  });

  it("searches collapsed company projects in WorkspaceSidebar via project-index and auto-expands match", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/v1/workspace/project-index") {
          return new Response(JSON.stringify({ ok: true, revision: 2, projects: { co_a: [], co_b: ["地铁二期项目"] }, truncated: false }), { status: 200 });
        }
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }),
    );

    const pinia = createPinia();
    setActivePinia(pinia);
    const router = createAppRouter(createMemoryHistory());
    await router.push("/");
    await router.isReady();
    const companies = useCompaniesStore();
    companies.list = { ok: true, revision: 2, companies: [COMPANY_A, COMPANY_B], monitored_company_id: "co_a", target_id: "t_a_0", watch_dir: "/合成/甲/成本发票", folder_roles: [] };

    const wrapper = mount(WorkspaceSidebar, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // Company B is collapsed initially
    expect(wrapper.text()).not.toContain("地铁二期项目");
    await wrapper.get('button[aria-label="搜索公司、项目或目录"]').trigger("click");
    await flushPromises();
    await wrapper.get('input[aria-label="搜索公司、项目或目录"]').setValue("地铁二期");
    await flushPromises();

    // Collapsed Company B automatically expands and shows the matched project; Company A is filtered out of tree
    expect(wrapper.get("nav.ws-tree").text()).toContain("乙公司");
    expect(wrapper.get("nav.ws-tree").text()).toContain("地铁二期项目");
    expect(wrapper.get("nav.ws-tree").text()).not.toContain("甲公司");
    expect(wrapper.text()).toContain("跨公司搜索发票「地铁二期」");
    wrapper.unmount();
  });
});

describe("Phase 2 WS-12 generic file browser and active invoice file actions", () => {
  it("renders WorkspaceFileBrowser for general folders and supports mkdir, rename, and native trash", async () => {
    const calls: { url: string; method: string; body?: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? "GET";
        const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
        calls.push({ url, method, body });
        if (url.endsWith("/directories")) {
          return new Response(JSON.stringify({ ok: true, revision: 2, company: COMPANY_A, directories: DIRS_A }), { status: 200 });
        }
        if (url.includes("/directories/cf_general/files?")) {
          return new Response(JSON.stringify({
            ok: true,
            company_id: "co_a",
            company_name: "甲公司",
            dir_key: "cf_general",
            dir_label: "合同归档",
            dir_role: "general",
            monitored: false,
            can_upload: true,
            can_mutate_existing: true,
            subpath: "",
            breadcrumbs: [{ name: "合同归档", subpath: "" }],
            folders: [{ name: "2026", relative_path: "2026", mtime: "2026-11-20 10:00:00", mtime_ns: 1, is_symlink: false }],
            files: [{ name: "采购合同.pdf", relative_path: "采购合同.pdf", ext: ".pdf", size_bytes: 2048, mtime: "2026-11-25 12:00:00", mtime_ns: 2, is_invoice_ext: true, is_symlink: false }],
            extensions: [".pdf"],
            total_folders: 1,
            total_files: 1,
            truncated: false,
          }), { status: 200 });
        }
        if (url.endsWith("/files/mkdir")) {
          return new Response(JSON.stringify({ ok: true, name: "补充协议", relative_path: "补充协议" }), { status: 200 });
        }
        if (url.endsWith("/files/trash/preview")) {
          return new Response(JSON.stringify({
            ok: true,
            job_id: "0123456789abcdef0123456789abcdef",
            company_id: "co_a",
            dir_key: "cf_general",
            dir_label: "合同归档",
            monitored: false,
            status: "prepared",
            file_count: 1,
            total_bytes: 2048,
            trashed: 0,
            failed: 0,
            unknown: 0,
            pending: 1,
            items: [{ relative_path: "采购合同.pdf", name: "采购合同.pdf", size_bytes: 2048, status: "pending", message: "" }],
            results: [],
            plan_hash: "hash_trash_1",
          }), { status: 200 });
        }
        if (url.endsWith("/files/trash/0123456789abcdef0123456789abcdef/confirm")) {
          return new Response(JSON.stringify({
            ok: true,
            job_id: "0123456789abcdef0123456789abcdef",
            company_id: "co_a",
            dir_key: "cf_general",
            dir_label: "合同归档",
            monitored: false,
            status: "completed",
            file_count: 1,
            total_bytes: 2048,
            trashed: 1,
            failed: 0,
            unknown: 0,
            pending: 0,
            items: [{ relative_path: "采购合同.pdf", name: "采购合同.pdf", size_bytes: 2048, status: "trashed", message: "已移入系统回收站。" }],
            results: [{ relative_path: "采购合同.pdf", name: "采购合同.pdf", size_bytes: 2048, status: "trashed", message: "已移入系统回收站。" }],
            plan_hash: "hash_trash_1",
          }), { status: 200 });
        }
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }),
    );

    setActivePinia(createPinia());
    const panel = mount(DirectoryPanel, { props: { company: COMPANY_A, dirKey: "cf_general" }, attachTo: document.body });
    await flushPromises();

    expect(panel.text()).toContain("目录文件与导入");
    expect(panel.text()).toContain("采购合同.pdf");

    // Create subfolder
    await panel.findAll("button").find((b) => b.text().includes("新建子文件夹"))!.trigger("click");
    await panel.get('input[aria-label="新建子文件夹名称"]').setValue("补充协议");
    await panel.get("form.ws-files__mkdir").trigger("submit");
    await flushPromises();
    expect(calls.some((c) => c.url.endsWith("/files/mkdir") && (c.body as { name?: string })?.name === "补充协议")).toBe(true);

    // Native recycle-bin confirmation flow (durable job_id confirm route)
    await panel.findAll("button").find((b) => b.text() === "回收站")!.trigger("click");
    await flushPromises();
    const dialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    const confirmBtn = dialog.findAll("button").find((b) => b.text().includes("确认移入系统回收站"))!;
    expect((confirmBtn.element as HTMLButtonElement).disabled).toBe(true);
    await dialog.get('input[type="checkbox"]').setValue(true);
    await confirmBtn.trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.url.endsWith("/files/trash/0123456789abcdef0123456789abcdef/confirm") && (c.body as { confirm?: boolean; plan_hash?: string })?.confirm === true && (c.body as { plan_hash?: string })?.plan_hash === "hash_trash_1")).toBe(true);

    panel.unmount();
  });

  it("locks trash confirmation on unknown response and recovers per-file receipt via read-only GET", async () => {
    const calls: { url: string; method: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? "GET";
        calls.push({ url, method });
        if (url.endsWith("/directories")) {
          return new Response(JSON.stringify({ ok: true, revision: 2, company: COMPANY_A, directories: DIRS_A }), { status: 200 });
        }
        if (url.includes("/directories/cf_general/files?")) {
          return new Response(JSON.stringify({
            ok: true,
            company_id: "co_a",
            company_name: "甲公司",
            dir_key: "cf_general",
            dir_label: "合同归档",
            dir_role: "general",
            monitored: false,
            can_upload: true,
            can_mutate_existing: true,
            subpath: "",
            breadcrumbs: [{ name: "合同归档", subpath: "" }],
            folders: [],
            files: [{ name: "采购合同.pdf", relative_path: "采购合同.pdf", ext: ".pdf", size_bytes: 2048, mtime: "2026-11-25 12:00:00", mtime_ns: 2, is_invoice_ext: true, is_symlink: false }],
            extensions: [".pdf"],
            total_folders: 0,
            total_files: 1,
            truncated: false,
          }), { status: 200 });
        }
        if (url.endsWith("/files/trash/preview")) {
          return new Response(JSON.stringify({
            ok: true,
            job_id: "fedcba9876543210fedcba9876543210",
            company_id: "co_a",
            dir_key: "cf_general",
            dir_label: "合同归档",
            monitored: false,
            status: "prepared",
            file_count: 1,
            total_bytes: 2048,
            trashed: 0,
            failed: 0,
            unknown: 0,
            pending: 1,
            items: [{ relative_path: "采购合同.pdf", name: "采购合同.pdf", size_bytes: 2048, status: "pending", message: "" }],
            results: [],
            plan_hash: "hash_trash_lost",
          }), { status: 200 });
        }
        if (url.endsWith("/files/trash/fedcba9876543210fedcba9876543210/confirm")) {
          throw new TypeError("network disconnected");
        }
        if (url.endsWith("/files/trash/fedcba9876543210fedcba9876543210") && method === "GET") {
          return new Response(JSON.stringify({
            ok: true,
            job_id: "fedcba9876543210fedcba9876543210",
            company_id: "co_a",
            dir_key: "cf_general",
            dir_label: "合同归档",
            monitored: false,
            status: "partial",
            file_count: 1,
            total_bytes: 2048,
            trashed: 0,
            failed: 1,
            unknown: 0,
            pending: 0,
            items: [{ relative_path: "采购合同.pdf", name: "采购合同.pdf", size_bytes: 2048, status: "failed", message: "回收站不可用" }],
            results: [{ relative_path: "采购合同.pdf", name: "采购合同.pdf", size_bytes: 2048, status: "failed", message: "回收站不可用" }],
            plan_hash: "hash_trash_lost",
          }), { status: 200 });
        }
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }),
    );

    setActivePinia(createPinia());
    const panel = mount(DirectoryPanel, { props: { company: COMPANY_A, dirKey: "cf_general" }, attachTo: document.body });
    await flushPromises();

    await panel.findAll("button").find((b) => b.text() === "回收站")!.trigger("click");
    await flushPromises();
    const dialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    await dialog.get('input[type="checkbox"]').setValue(true);
    await dialog.findAll("button").find((b) => b.text().includes("确认移入系统回收站"))!.trigger("click");
    await flushPromises();

    // Confirm button is replaced with read-only lookup; never invites blind retry
    expect(dialog.findAll("button").some((b) => b.text().includes("确认移入系统回收站"))).toBe(false);
    const lookupBtn = dialog.findAll("button").find((b) => b.text().includes("查询本次删除结果"))!;
    await lookupBtn.trigger("click");
    await flushPromises();

    expect(calls.some((c) => c.url.endsWith("/files/trash/fedcba9876543210fedcba9876543210") && c.method === "GET")).toBe(true);
    expect(dialog.text()).toContain("回收站不可用");
    expect(dialog.text()).toContain("失败");
    panel.unmount();
  });

  it("removes completed files from upload queue on partial failure and retries only remaining files", async () => {
    const uploadedNames: string[] = [];
    const previewBatches: string[][] = [];
    let secondAttempts = 0;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
        if (url.endsWith("/directories")) {
          return new Response(JSON.stringify({ ok: true, revision: 2, company: COMPANY_A, directories: DIRS_A }), { status: 200 });
        }
        if (url.includes("/directories/cf_general/files?")) {
          return new Response(JSON.stringify({
            ok: true,
            company_id: "co_a",
            company_name: "甲公司",
            dir_key: "cf_general",
            dir_label: "合同归档",
            dir_role: "general",
            monitored: false,
            can_upload: true,
            can_mutate_existing: true,
            subpath: "",
            breadcrumbs: [{ name: "合同归档", subpath: "" }],
            folders: [],
            files: [],
            extensions: [],
            total_folders: 0,
            total_files: 0,
            truncated: false,
          }), { status: 200 });
        }
        if (url.endsWith("/files/import-preview")) {
          const names = (body as { filenames: string[] }).filenames;
          previewBatches.push(names);
          return new Response(JSON.stringify({
            ok: true,
            company_id: "co_a",
            dir_key: "cf_general",
            subpath: "",
            conflict_policy: "rename",
            monitored: false,
            items: names.map((name) => ({ original_name: name, target_name: name, action: "write", conflict: false, reason: "" })),
            summary: { write: names.length, rename: 0, skip: 0, blocked: 0 },
          }), { status: 200 });
        }
        if (url.includes("/files/upload?")) {
          const filename = new URL(url, "http://localhost").searchParams.get("filename") ?? "";
          uploadedNames.push(filename);
          if (filename === "second.pdf" && secondAttempts === 0) {
            secondAttempts += 1;
            return new Response(JSON.stringify({ detail: "磁盘临时繁忙" }), { status: 500 });
          }
          return new Response(JSON.stringify({
            ok: true,
            status: "imported",
            original_name: filename,
            saved_name: filename,
            relative_path: filename,
            size_bytes: 5,
            monitored: false,
            message: `已导入「${filename}」。`,
          }), { status: 200 });
        }
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }),
    );

    setActivePinia(createPinia());
    const panel = mount(DirectoryPanel, { props: { company: COMPANY_A, dirKey: "cf_general" }, attachTo: document.body });
    await flushPromises();

    // Stage 2 files via dropzone
    const f1 = new File(["aaa"], "first.pdf", { type: "application/pdf" });
    const f2 = new File(["bbb"], "second.pdf", { type: "application/pdf" });
    await panel.get(".ws-files__dropzone").trigger("drop", { dataTransfer: { files: [f1, f2] } });
    await flushPromises();
    expect(previewBatches).toEqual([["first.pdf", "second.pdf"]]);

    // First confirm: first.pdf succeeds, second.pdf fails
    await panel.findAll("button").find((b) => b.text().includes("确认导入"))!.trigger("click");
    await flushPromises();

    expect(panel.text()).toContain("磁盘临时繁忙");
    expect(panel.text()).toContain("待导入 1 个文件");
    expect(previewBatches).toEqual([["first.pdf", "second.pdf"], ["second.pdf"]]);

    // Retry confirm: must upload ONLY second.pdf, never re-uploading first.pdf
    await panel.findAll("button").find((b) => b.text().includes("确认导入"))!.trigger("click");
    await flushPromises();

    expect(uploadedNames).toEqual(["first.pdf", "second.pdf", "second.pdf"]);
    expect(panel.text()).not.toContain("待导入");
    panel.unmount();
  });

  it("freezes upload destination during in-flight batch and keeps partial move receipt modal open", async () => {
    const uploadSubpaths: string[] = [];
    let releaseFirstUpload: (() => void) | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
        if (url === "/api/v1/companies") {
          return new Response(JSON.stringify({ ok: true, revision: 2, companies: [COMPANY_A], monitored_company_id: "co_a", target_id: "t_a_0", watch_dir: "/合成/甲/成本发票", folder_roles: [] }), { status: 200 });
        }
        if (url.endsWith("/directories")) {
          return new Response(JSON.stringify({ ok: true, revision: 2, company: COMPANY_A, directories: DIRS_A }), { status: 200 });
        }
        if (url.includes("/directories/cf_general/files?")) {
          const parsed = new URL(url, "http://localhost");
          const curSub = parsed.searchParams.get("subpath") ?? "";
          return new Response(JSON.stringify({
            ok: true,
            company_id: "co_a",
            company_name: "甲公司",
            dir_key: "cf_general",
            dir_label: "合同归档",
            dir_role: "general",
            monitored: false,
            can_upload: true,
            can_mutate_existing: true,
            subpath: curSub,
            breadcrumbs: curSub ? [{ name: "合同归档", subpath: "" }, { name: curSub, subpath: curSub }] : [{ name: "合同归档", subpath: "" }],
            folders: curSub ? [] : [{ name: "2026", relative_path: "2026", mtime: "2026-11-20 10:00:00", mtime_ns: 1, is_symlink: false }],
            files: [{ name: "采购合同.pdf", relative_path: curSub ? `${curSub}/采购合同.pdf` : "采购合同.pdf", ext: ".pdf", size_bytes: 2048, mtime: "2026-11-25 12:00:00", mtime_ns: 2, is_invoice_ext: true, is_symlink: false }],
            extensions: [".pdf"],
            total_folders: curSub ? 0 : 1,
            total_files: 1,
            truncated: false,
          }), { status: 200 });
        }
        if (url.endsWith("/files/import-preview")) {
          const names = (body as { filenames: string[] }).filenames;
          return new Response(JSON.stringify({
            ok: true,
            company_id: "co_a",
            dir_key: "cf_general",
            subpath: "",
            conflict_policy: "rename",
            monitored: false,
            items: names.map((name) => ({ original_name: name, target_name: name, action: "write", conflict: false, reason: "" })),
            summary: { write: names.length, rename: 0, skip: 0, blocked: 0 },
          }), { status: 200 });
        }
        if (url.includes("/files/upload?")) {
          const parsed = new URL(url, "http://localhost");
          const filename = parsed.searchParams.get("filename") ?? "";
          uploadSubpaths.push(`${filename}@${parsed.searchParams.get("subpath") ?? ""}`);
          if (filename === "a.pdf") {
            await new Promise<void>((resolve) => {
              releaseFirstUpload = resolve;
            });
          }
          return new Response(JSON.stringify({
            ok: true,
            status: "imported",
            original_name: filename,
            saved_name: filename,
            relative_path: filename,
            size_bytes: 5,
            monitored: false,
            message: `已导入「${filename}」。`,
          }), { status: 200 });
        }
        if (url.endsWith("/files/move/preview")) {
          return new Response(JSON.stringify({
            ok: true,
            job_id: "11111111111111111111111111111111",
            company_id: "co_a",
            company_name: "甲公司",
            dir_key: "cf_general",
            dir_label: "合同归档",
            conflict_policy: "reject",
            plan_hash: "move_hash_partial",
            status: "prepared",
            can_confirm: true,
            summary: { move: 1, rename: 0, conflict: 0, blocked: 0 },
            items: [{
              relative_path: "采购合同.pdf",
              source_name: "采购合同.pdf",
              target_company_id: "co_a",
              target_company_name: "甲公司",
              target_dir_key: "expense_reimbursement_dir",
              target_dir_label: "费用报销",
              target_subpath: "",
              target_name: "采购合同.pdf",
              action: "move",
              reason: "",
            }],
            results: [],
          }), { status: 200 });
        }
        if (url.endsWith("/files/move/11111111111111111111111111111111/confirm")) {
          return new Response(JSON.stringify({
            ok: true,
            job_id: "11111111111111111111111111111111",
            company_id: "co_a",
            company_name: "甲公司",
            dir_key: "cf_general",
            dir_label: "合同归档",
            conflict_policy: "reject",
            plan_hash: "move_hash_partial",
            status: "partial",
            can_confirm: true,
            summary: { move: 1, rename: 0, conflict: 0, blocked: 0 },
            items: [{
              relative_path: "采购合同.pdf",
              source_name: "采购合同.pdf",
              target_company_id: "co_a",
              target_company_name: "甲公司",
              target_dir_key: "expense_reimbursement_dir",
              target_dir_label: "费用报销",
              target_subpath: "",
              target_name: "采购合同.pdf",
              action: "move",
              reason: "",
            }],
            moved: 0,
            failed: 1,
            unknown: 0,
            pending: 0,
            results: [{
              relative_path: "采购合同.pdf",
              target_company_id: "co_a",
              target_dir_key: "expense_reimbursement_dir",
              target_name: "采购合同.pdf",
              status: "failed",
              message: "目标文件已存在",
            }],
          }), { status: 200 });
        }
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }),
    );

    setActivePinia(createPinia());
    const companiesStore = useCompaniesStore();
    await companiesStore.load();
    const panel = mount(DirectoryPanel, { props: { company: COMPANY_A, dirKey: "cf_general" }, attachTo: document.body });
    await flushPromises();

    // 1) Freeze upload destination while navigating subfolder during in-flight upload
    const fa = new File(["a"], "a.pdf", { type: "application/pdf" });
    const fb = new File(["b"], "b.pdf", { type: "application/pdf" });
    await panel.get(".ws-files__dropzone").trigger("drop", { dataTransfer: { files: [fa, fb] } });
    await flushPromises();
    const uploadClick = panel.findAll("button").find((b) => b.text().includes("确认导入"))!.trigger("click");
    await flushPromises();
    // Folder navigation buttons are disabled while uploading; attempting click cannot change subpath
    const enterBtn = panel.findAll("button").find((b) => b.text() === "进入")!;
    expect((enterBtn.element as HTMLButtonElement).disabled).toBe(true);
    await enterBtn.trigger("click");
    releaseFirstUpload!();
    await uploadClick;
    await flushPromises();
    expect(uploadSubpaths).toEqual(["a.pdf@", "b.pdf@"]);

    // 2) Partial move keeps FileMoveModal open with per-file receipt visible
    await panel.findAll("button").find((b) => b.text() === "移动")!.trigger("click");
    await flushPromises();
    const dialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    await dialog.findAll("button").find((b) => b.text().includes("预览移动计划"))!.trigger("click");
    await flushPromises();
    await dialog.findAll("button").find((b) => b.text().includes("确认移动"))!.trigger("click");
    await flushPromises();

    expect(document.body.querySelector('[role="dialog"]')).not.toBeNull();
    expect(dialog.text()).toContain("目标文件已存在");
    expect(dialog.text()).toContain("执行回执");
    // Controls remain locked once receipt is present
    expect((dialog.get('select[aria-label="移动目标目录"]').element as HTMLSelectElement).disabled).toBe(true);
    panel.unmount();
  });

  it("exposes manual edit/rename/move on active monitored invoice row and hides them on read-only directory", async () => {
    const calls: { url: string; method: string; body?: unknown }[] = [];
    const invoiceRow = {
      invoice_key: "0",
      source_file: "sample.xml",
      source_path: "/合成/甲/成本发票/sample.xml",
      file_type: "xml",
      invoice_number: "11001",
      invoice_date: "2026-11-10",
      seller: "原销售方",
      buyer: "甲公司",
      amount: "500.00",
      tax_rate: "13%",
      status: "已识别",
      tags: [],
    };
    let readOnlyMode = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? "GET";
        const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
        calls.push({ url, method, body });
        if (url === "/api/v1/invoice-tags") {
          return new Response(JSON.stringify({ ok: true, revision: 1, tags: [] }), { status: 200 });
        }
        if (url.includes("/directories/cost_invoice_dir/invoices")) {
          return new Response(JSON.stringify({
            ok: true,
            count: 1,
            page: 1,
            page_size: 100,
            read_only: readOnlyMode,
            directory: { ...DIRS_A[0], active: !readOnlyMode, read_only: readOnlyMode },
            items: [invoiceRow],
          }), { status: 200 });
        }
        if (url.endsWith("/manual-fields")) {
          return new Response(JSON.stringify({ ok: true, updated: true, invoice_key: "0" }), { status: 200 });
        }
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }),
    );

    setActivePinia(createPinia());
    const activeWrap = mount(DirectoryInvoices, { props: { company: COMPANY_A, dirKey: "cost_invoice_dir" }, attachTo: document.body });
    await flushPromises();

    await activeWrap.get("tbody tr").trigger("contextmenu");
    await flushPromises();
    expect(activeWrap.text()).toContain("编辑手改字段…");
    expect(activeWrap.text()).toContain("重命名原文件…");
    expect(activeWrap.text()).toContain("移动到其他目录…");

    // Open manual edit modal and save edited buyer + seller
    await activeWrap.findAll('[role="menuitem"]').find((b) => b.text() === "编辑手改字段…")!.trigger("click");
    await flushPromises();
    const dialog = new DOMWrapper(document.body.querySelector('[role="dialog"]')!);
    await dialog.get('input[aria-label="手改销售方"]').setValue("新销售方");
    await dialog.get('input[aria-label="手改购买方"]').setValue("新购买方");
    await dialog.get("form").trigger("submit");
    await flushPromises();
    const patchCall = calls.find((c) => c.url.endsWith("/api/v1/invoices/0/manual-fields") && c.method === "PATCH");
    expect(patchCall?.body).toEqual({
      fields: { 销售方: "新销售方", 购买方: "新购买方" },
      source_path: "/合成/甲/成本发票/sample.xml",
      target_id: "t_a_0",
    });
    activeWrap.unmount();

    // Non-monitored read-only directory must NOT expose manual edit / rename / move
    readOnlyMode = true;
    const roWrap = mount(DirectoryInvoices, { props: { company: { ...COMPANY_A, monitored: false, monitored_subdir_key: null }, dirKey: "cost_invoice_dir" }, attachTo: document.body });
    await flushPromises();
    await roWrap.get("tbody tr").trigger("contextmenu");
    await flushPromises();
    expect(roWrap.text()).not.toContain("编辑手改字段…");
    expect(roWrap.text()).not.toContain("重命名原文件…");
    expect(roWrap.text()).not.toContain("移动到其他目录…");
    roWrap.unmount();
  });
});
