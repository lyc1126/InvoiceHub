import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import ServerConnectModal from "../src/components/ServerConnectModal.vue";
import ServerDirectoryPanel from "../src/components/ServerDirectoryPanel.vue";
import ServerSourcesPanel from "../src/components/ServerSourcesPanel.vue";

const sid = "a".repeat(32);
const folder = "b".repeat(32);
const file = "c".repeat(32);
const file2 = "d".repeat(32);

function setup(online = true, unsupported = false, withSummary = false) {
  const source = {
    id: sid,
    name: "合成服务器",
    protocol: "mounted",
    root: "/synthetic/share",
    revision: 1,
    connection: online ? "online" : "offline",
    sync: "idle",
    error: "",
    fingerprints: [],
    generation: "g1",
    snapshot: "current",
    last_complete_at: "2026-11-19T00:00:00Z",
    cached_count: 1,
    entry_count: 2,
    cache_budget: 256 * 1024 ** 2,
    binding: { company_id: "saved-company", role: "issued_invoice_dir" },
  };
  const summaryRows = [
    {
      entry_id: file,
      invoice_key: file,
      relative: "子目录/合成.xml",
      source_path: file,
      source_file: "合成.xml",
      file_format: "XML",
      invoice_number: "25322000000043426430",
      invoice_type: "增值税专用发票",
      business_type: "标准电子发票",
      classification_status: "ok",
      classification_issue: "",
      tax_rate: "0.13",
      invoice_date: "2026-11-01",
      amount: "1130.00",
      tax_amount: "130.00",
      pretax_amount: "1000.00",
      seller: "示例销售有限公司",
      buyer: "示例采购有限公司",
      duplicate: false,
      status: "已识别",
      cached: true,
    },
    {
      entry_id: file2,
      invoice_key: file2,
      relative: "子目录/待核对.pdf",
      source_path: file2,
      source_file: "待核对.pdf",
      file_format: "PDF",
      invoice_number: "",
      invoice_type: "",
      business_type: "",
      classification_status: "needs_review",
      classification_issue: "",
      tax_rate: "",
      invoice_date: "",
      amount: "",
      tax_amount: "",
      pretax_amount: "",
      seller: "",
      buyer: "",
      duplicate: false,
      status: "待核对",
      cached: true,
    },
  ];
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url);
    let body: unknown = { ok: true };
    if (path === "/api/v1/sources") {
      body = { sources: [source] };
    } else if (path === "/api/v1/sources/mounted-shares") {
      body = { ok: true, shares: [{ name: "财务共享", path: "/Volumes/财务共享", remote: "//nas/财务共享", fs_type: "smbfs" }] };
    } else if (path === `/api/v1/sources/${sid}`) {
      body = { ok: true, source };
    } else if (path.includes("/entries")) {
      const inside = new URL(path, "http://localhost").searchParams.get("parent_id") === folder;
      body = {
        source,
        items: inside
          ? [{ id: file, name: unsupported ? "说明.txt" : "合成.xml", relative: "子目录/合成.xml", kind: "file", size: 42, cached: false }]
          : [{ id: folder, name: "子目录", relative: "子目录", kind: "directory", size: 0, cached: false }],
        count: 1,
        page: 1,
        scope: { files: 1, bytes: 42, readable_files: unsupported ? 0 : 1 },
        breadcrumbs: [{ id: "", name: source.name }, ...(inside ? [{ id: folder, name: "子目录" }] : [])],
      };
    } else if (path.includes("/summary")) {
      if (!withSummary) {
        body = { available: false, breadcrumbs: [{ id: "", name: source.name }, { id: folder, name: "子目录" }], scope_name: "子目录" };
      } else {
        const params = new URL(path, "http://localhost").searchParams;
        const st = params.get("status") ?? "";
        const filtered = st ? summaryRows.filter((row) => row.status === st) : summaryRows;
        body = {
          available: true,
          generation: "sumgen1",
          last_complete_at: "2026-11-24T10:00:00Z",
          stale: !online,
          items: filtered,
          count: filtered.length,
          total_count: summaryRows.length,
          page: 1,
          page_size: 50,
          breadcrumbs: [{ id: "", name: source.name }, { id: folder, name: "子目录" }],
          scope_parent_id: folder,
          scope_name: "子目录",
          invoice_stats: {
            all: { total: 2, recognized: 1, needs_review: 1, duplicates: 0, total_amount: "1130.00", total_amount_valid_count: 1, total_amount_missing_count: 1, total_amount_conflict_count: 0 },
            filtered: { total: filtered.length, recognized: filtered.filter((r) => r.status === "已识别").length, needs_review: filtered.filter((r) => r.status === "待核对").length, duplicates: 0, total_amount: "1130.00", total_amount_valid_count: 1, total_amount_missing_count: filtered.length - 1, total_amount_conflict_count: 0 },
          },
          ledger: { totals: { input: { count: 1, total: "1130.00", pretax: "1000.00", tax: "130.00" } } },
          stats: { parsed: 1, reused: 1 },
          scope: "来源票面只读汇总；公司模块尚未接入，不能作为正式做账或税款。",
        };
      }
    } else if (path.endsWith("/selection-summary")) {
      body = {
        ok: true,
        selection: { record_count: 1, invoice_count: 1, collapsed_record_count: 0 },
        totals: {
          pretax_amount: { value: 1000, valid_invoice_count: 1, missing_invoice_count: 0, conflict_invoice_count: 0 },
          tax_amount: { value: 130, valid_invoice_count: 1, missing_invoice_count: 0, conflict_invoice_count: 0 },
          total_with_tax: { value: 1130, valid_invoice_count: 1, missing_invoice_count: 0, conflict_invoice_count: 0 },
        },
        cost_breakdown: {
          available: true,
          matched_invoice_count: 1,
          unmatched_invoice_count: 0,
          detail_count: 1,
          projects: [
            {
              project_name: "钢材",
              display_project_name: "钢材",
              tax_rate: "13%",
              display_tax_rate: "13%",
              quantity_total: 10,
              amount_pretax_total: 1000,
              total_with_tax: 1130,
              specs: [{ specification: "DN25", unit: "吨", quantity_total: 10, arithmetic_average_unit_price_pretax: 100, weighted_average_unit_price_pretax: 100, weighted_average_unit_price_with_tax: 113 }],
              source_invoices: [{ invoice_key: file, source_path: file, file_name: "合成.xml", invoice_number: "25322000000043426430" }],
            },
          ],
        },
      };
    } else if (path.endsWith("/tasks")) {
      body = { source };
    } else if (path.endsWith("/previews") && init?.method === "POST") {
      body = {
        job_id: "opaque-job",
        preview_type: "text",
        page_count: 0,
        stale: !online,
        verified_at: "2026-11-19",
        source_id: sid,
        entry_id: file,
        record_count: 1,
        idle_timeout_seconds: 900,
        keep_alive_url: `/api/v1/sources/${sid}/previews/opaque-job/keep-alive`,
        files: [
          {
            file_number: 1,
            entry_id: file,
            name: "合成.xml",
            preview_type: "text",
            page_count: 0,
            reason: "",
            stale: !online,
            verified_at: "2026-11-19",
            page_url_template: `/api/v1/sources/${sid}/previews/opaque-job/files/1/pages/{page_number}`,
            text_url: `/api/v1/sources/${sid}/previews/opaque-job/files/1/text`,
          },
        ],
      };
    } else if (path.endsWith("/files/1/text")) {
      return new Response("<Invoice>合成批量</Invoice>", { status: 200 });
    } else if (path.endsWith("/text")) {
      body = { text: "<Invoice>合成</Invoice>" };
    }
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("服务器只读来源面板与工作区视图", () => {
  it("按不透明目录与文件标识浏览，支持按当前目录汇总并派发主工作区打开事件", async () => {
    const fetch = setup();
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.get('[aria-label="切换服务器目录"]').setValue(folder);
    await flushPromises();
    expect(wrapper.text()).toContain("合成.xml");

    // Clicking "汇总此目录" scopes the summary task to the selected parent_id.
    await wrapper.findAll("button").find((b) => b.text() === "汇总此目录")!.trigger("click");
    await flushPromises();
    const summaryTask = fetch.mock.calls.find(([url, init]) => url.endsWith("/tasks") && String(init?.body).includes('"summary"'));
    expect(JSON.parse(String(summaryTask?.[1]?.body))).toEqual({ kind: "summary", parent_id: folder });

    // Opening a file switches to its horizontal tab and previews it.
    const open = wrapper.findAll(".server-files button")[0]!;
    await open.trigger("click");
    await flushPromises();
    expect(wrapper.get("pre").text()).toContain("<Invoice>合成</Invoice>");
    const download = fetch.mock.calls.find(([url, init]) => url.endsWith("/tasks") && String(init?.body).includes('"download"'));
    expect(JSON.parse(String(download?.[1]?.body))).toEqual({ kind: "download", entry_id: file });
    expect(fetch.mock.calls.some(([url]) => url.includes(`/entries?parent_id=${folder}`))).toBe(true);
    expect(fetch.mock.calls.some(([url]) => url.includes("/invoices/"))).toBe(false);

    await wrapper.get('[aria-label="放大文件面板"]').trigger("click");
    expect(wrapper.get(".server-panel").classes()).toContain("server-panel--wide");
    await wrapper.get('[aria-label="收起服务器文件"]').trigger("click");
    expect(wrapper.emitted("close")).toHaveLength(1);
    wrapper.unmount();
  });

  it("离线副本明确标记，连接弹窗自动发现挂载共享且 SSH 不提供密码输入", async () => {
    const fetch = setup(false);
    const pinia = createPinia();
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [pinia] } });
    await flushPromises();
    await wrapper.get('[aria-label="切换服务器目录"]').setValue(folder);
    await flushPromises();
    expect(wrapper.get(".server-files button").text()).toContain("查看离线副本");
    await wrapper.get(".server-files button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("离线副本（可能过期）");
    const preview = fetch.mock.calls.find(([url]) => url.endsWith("/previews"));
    expect(JSON.parse(String(preview?.[1]?.body)).allow_stale).toBe(true);
    expect(fetch.mock.calls.some(([url]) => url.endsWith("/tasks"))).toBe(false);
    await wrapper.findAll("button").find((b) => b.text() === "返回目录")!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("公司、做账、税费等模块尚未接入");
    wrapper.unmount();

    const modal = mount(ServerConnectModal, {
      props: { open: true },
      global: { plugins: [pinia], stubs: { Teleport: true } },
    });
    await flushPromises();
    expect(modal.text()).toContain("财务共享");
    await modal.findAll('[role="tab"]')[1]!.trigger("click");
    expect(modal.text()).toContain("SSH Agent");
    expect(modal.find('input[type="password"]').exists()).toBe(false);
    modal.unmount();
  });

  it("收起面板释放预览租约", async () => {
    const fetch = setup(false);
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.get('[aria-label="切换服务器目录"]').setValue(folder);
    await flushPromises();
    await wrapper.get(".server-files button").trigger("click");
    await flushPromises();
    await wrapper.setProps({ open: false });
    await flushPromises();
    expect(fetch.mock.calls.some(([url, init]) => url.endsWith("/previews/opaque-job") && init?.method === "DELETE")).toBe(true);
    wrapper.unmount();
  });

  it("只有不支持格式仍可查元信息，空内容与筛选无匹配分开提示", async () => {
    setup(true, true);
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.get('[aria-label="切换服务器目录"]').setValue(folder);
    await flushPromises();
    expect(wrapper.text()).toContain("说明.txt");
    expect(wrapper.text()).toContain("无可读取的文件");
    await wrapper.get('[aria-label="筛选服务器文件"]').setValue("说明");
    expect(wrapper.text()).not.toContain("没有匹配的文件");
    expect(wrapper.text()).not.toContain("无可读取的文件");
    wrapper.unmount();
  });

  it("首次打开和重开都恢复已保存缓存预算与角色", async () => {
    setup();
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [createPinia()] } });
    await flushPromises();
    expect((wrapper.get('details input[type="number"]').element as HTMLInputElement).value).toBe("256");
    expect((wrapper.findAll("details select")[1]!.element as HTMLSelectElement).value).toBe("issued_invoice_dir");
    await wrapper.get('details input[type="number"]').setValue("512");
    await wrapper.setProps({ open: false });
    await wrapper.setProps({ open: true });
    await flushPromises();
    expect((wrapper.get('details input[type="number"]').element as HTMLInputElement).value).toBe("256");
    wrapper.unmount();
  });

  it("主工作区服务器目录视图支持四项统计、筛选排序、勾选合计详情和批量原票预览", async () => {
    const fetch = setup(true, false, true);
    const wrapper = mount(ServerDirectoryPanel, {
      props: { sourceId: sid, parentId: folder, active: true },
      global: { plugins: [createPinia()], stubs: { Teleport: true } },
    });
    await flushPromises();

    // Native 4 KPI cards and multi-column invoice rows.
    expect(wrapper.text()).toContain("示例销售有限公司");
    expect(wrapper.text()).toContain("示例采购有限公司");
    expect(wrapper.text()).toContain("25322000000043426430");
    expect(wrapper.text()).toContain("1,130.00");

    // Server-side status filter updates query and results.
    await wrapper.get('select[aria-label="状态"]').setValue("已识别");
    await flushPromises();
    expect(fetch.mock.calls.some(([url]) => url.includes("status=%E5%B7%B2%E8%AF%86%E5%88%AB"))).toBe(true);

    // Check first row -> selection bar calls selection-summary and opens cost breakdown modal.
    await wrapper.get(`input[aria-label="勾选 25322000000043426430"]`).setValue(true);
    await new Promise((resolve) => setTimeout(resolve, 160));
    await flushPromises();
    expect(fetch.mock.calls.some(([url]) => url.endsWith("/selection-summary"))).toBe(true);
    expect(wrapper.text()).toContain("合计详情");

    await wrapper.get(".sb-sum").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("DN25");
    expect(wrapper.text()).toContain("钢材");

    // Batch preview opens ServerPreviewDrawer using /api/v1/sources/{sid}/previews and releases on close.
    await wrapper.get(".sb-btn").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("<Invoice>合成批量</Invoice>");
    await wrapper.get('[aria-label="关闭原票"]').trigger("click");
    await flushPromises();
    expect(fetch.mock.calls.some(([url, init]) => url.endsWith("/previews/opaque-job") && init?.method === "DELETE")).toBe(true);
    wrapper.unmount();
  });
});
