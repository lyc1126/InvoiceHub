import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import App from "../src/App.vue";
import { createAppRouter } from "../src/router";
import { useSystemStore } from "../src/stores/system";
import { CONTENT_MIN, SIDEBAR_MAX, SIDEBAR_MIN, clampSidebar } from "../src/stores/workspace";

const HEALTH = { ok: true, product_version: "0.3.0-alpha.2", platform: "macos", background_status: "ready", watch_dir: "/tmp/合成目录", target_id: "t1" };
const SETTINGS = { ok: true, watch_dir: "/tmp/合成目录", active_target_id: "t1" };
const SUBDIRS = [
  { key: "cost_invoice_dir", label: "成本发票", relative_path: "成本发票", path: "/合成/甲/成本发票", status: "present" },
  { key: "issued_invoice_dir", label: "开具发票", relative_path: "开具发票", path: "/合成/甲/开具发票", status: "present" },
  { key: "payroll_social_dir", label: "工资社保", relative_path: "工资社保", path: "/合成/甲/工资社保", status: "present" },
];
const COMPANY = {
  id: "co_1", name: "甲公司", root_dir: "/合成/甲", root_path: "/合成/甲", root_status: "present", subdirs: SUBDIRS,
  missing_subdir_count: 0, taxpayer_periods: [], current_taxpayer_type: "general", current_taxpayer_label: "一般纳税人",
  monitored: true, monitored_subdir_key: "cost_invoice_dir",
};
const OTHER = { ...COMPANY, id: "co_2", name: "乙公司有一个很长很长的名字", monitored: false, monitored_subdir_key: null };
const directories = (company: { monitored: boolean }) => SUBDIRS.map((item) => ({
  ...item, target_id: `t-${item.key}`, active: company.monitored && item.key === "cost_invoice_dir", read_only: item.key !== "cost_invoice_dir",
  projection: { summary_exists: false, summary_updated_at: "", cost_detail_exists: false, cost_detail_updated_at: "" },
  freshness: { state: "never_built", message: "" },
}));

let calls: string[] = [];
function stubBackend({ fail = false, companies = [COMPANY, OTHER] } = {}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (fail) return new Response(JSON.stringify({ detail: "服务暂不可用" }), { status: 503 });
      let body: unknown = SETTINGS;
      if (url.endsWith("/health")) body = HEALTH;
      else if (url === "/api/v1/companies") body = { ok: true, revision: 1, companies, monitored_company_id: companies.length ? "co_1" : null, target_id: "t1", watch_dir: "" };
      else if (url.includes("/directories") && !url.includes("/invoices")) body = { ok: true, revision: 1, company: COMPANY, directories: directories(url.includes("co_2") ? OTHER : COMPANY) };
      else if (url.includes("/invoices")) body = { ok: true, count: 0, page: 1, page_size: 50, read_only: true, directory: directories(COMPANY)[1], items: [] };
      else if (url.includes("/projects")) body = { ok: true, basis_label: "", assignments_revision: 0, projects: [{ project: "滨江一期", unassigned: false, input: {}, output: {}, face_difference_pretax: "0.00", periods: [] }], project_names: [], unassigned_invoices: [], manual_invoices: [], warnings: [], checks: [], checks_ok: true };
      else if (url.includes("/compare")) body = { ok: true, relation: "inventory", state: "no_details", message: "两个目录都还没有成本明细。", warnings: [], checks: [], checks_ok: true };
      else if (url === "/api/v1/invoice-tags") body = { ok: true, revision: 1, tags: [] };
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
}

async function mountApp(path = "/") {
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  const wrapper = mount(App, { global: { plugins: [pinia, router] }, attachTo: document.body });
  await flushPromises();
  return { wrapper, router };
}

const tabTitles = (wrapper: Awaited<ReturnType<typeof mountApp>>["wrapper"]) => wrapper.findAll(".ws-tab__title").map((item) => item.text());
const sidebarButton = (wrapper: Awaited<ReturnType<typeof mountApp>>["wrapper"], label: string) =>
  wrapper.findAll(".ws-sidebar .ws-node").find((item) => item.attributes("aria-label")?.startsWith(label))!;

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

describe("workspace shell", () => {
  it("shows the start page with the health snapshot when no company is registered", async () => {
    stubBackend({ companies: [] });
    const { wrapper } = await mountApp();
    expect(wrapper.get('[aria-label="起始页"]').text()).toContain("0.3.0-alpha.2");
    expect(wrapper.text()).toContain("/tmp/合成目录");
    expect(wrapper.find(".ws-tab").exists()).toBe(false);
  });

  it("sends earlier module paths to the home module", async () => {
    stubBackend();
    const { router } = await mountApp("/companies");
    expect(router.currentRoute.value.name).toBe("home");
  });

  it("links modules that are not migrated yet to their classic pages", async () => {
    stubBackend();
    const { wrapper } = await mountApp();
    const hrefs = wrapper.findAll(".rail a").map((item) => item.attributes("href"));
    expect(hrefs).toEqual(expect.arrayContaining(["/costs", "/documents", "/bookkeeping", "/ocr", "/consistency", "/settings", "/"]));
  });

  it("keeps the last good snapshot when a refresh fails", async () => {
    stubBackend({ companies: [] });
    const { wrapper } = await mountApp();
    stubBackend({ fail: true });
    await useSystemStore().refresh();
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("服务暂不可用");
    expect(wrapper.text()).toContain("0.3.0-alpha.2");
  });
});

describe("workspace home", () => {
  it("opens sidebar nodes as tabs once, keeps them mounted and returns to the start page after the last close", async () => {
    stubBackend();
    const { wrapper } = await mountApp();
    expect(tabTitles(wrapper)).toEqual(["甲公司"]); // the monitored company opens on the first visit
    await wrapper.get('.ws-toggle[aria-label="展开 甲公司"]').trigger("click");
    await flushPromises();
    await sidebarButton(wrapper, "开具发票").trigger("click");
    await flushPromises();
    await sidebarButton(wrapper, "开具发票").trigger("click"); // same node: no second tab
    await flushPromises();
    expect(tabTitles(wrapper)).toEqual(["甲公司", "甲公司 · 开具发票"]);
    expect(wrapper.text()).toContain("只读 · 上次汇总");
    // The company tab is hidden, not destroyed: its directory table is still in the DOM.
    const panels = wrapper.findAll('[role="tabpanel"][id^="ws-panel-"]');
    expect(panels).toHaveLength(2);
    expect((panels[0]!.element as HTMLElement).style.display).toBe("none");
    for (const close of wrapper.findAll(".ws-tab__close")) await close.trigger("click");
    await flushPromises();
    expect(wrapper.find('[aria-label="起始页"]').exists()).toBe(true);
    // The start page stays empty after a list reload instead of reopening the monitored company.
    await wrapper.get(".ws-brand").trigger("click");
    await wrapper.findAll(".ws-menu--head button")[0]!.trigger("click");
    await flushPromises();
    expect(wrapper.find(".ws-tab").exists()).toBe(false);
  });

  it("loads projects only when a company is expanded and opens a project tab", async () => {
    stubBackend();
    const { wrapper } = await mountApp();
    expect(calls.some((url) => url.includes("/projects"))).toBe(false);
    await wrapper.get('.ws-toggle[aria-label="展开 甲公司"]').trigger("click");
    await flushPromises();
    await sidebarButton(wrapper, "项目 滨江一期").trigger("click");
    await flushPromises();
    expect(tabTitles(wrapper)).toContain("甲公司 · 滨江一期");
  });

  it("pins a node from the keyboard menu and remembers it", async () => {
    stubBackend();
    const { wrapper } = await mountApp();
    const node = sidebarButton(wrapper, "乙公司");
    await node.trigger("keydown", { key: "F10", shiftKey: true });
    const menu = wrapper.get('.ws-sidebar [role="menu"]');
    expect(document.activeElement?.textContent).toBe("在标签中打开");
    await menu.findAll("button").find((item) => item.text() === "置顶")!.trigger("click");
    await flushPromises();
    expect(wrapper.find('.ws-sidebar [role="menu"]').exists()).toBe(false);
    expect(wrapper.findAll(".ws-section").map((item) => item.text())).toContain("置顶");
    expect(JSON.parse(localStorage.getItem("invoicehub.workspace.v1")!).pins).toEqual(["company:co_2"]);
  });

  it("compares two folders of one company and refuses unrelated pairs", async () => {
    stubBackend();
    const { wrapper } = await mountApp();
    await wrapper.get('.ws-toggle[aria-label="展开 甲公司"]').trigger("click");
    await wrapper.get('.ws-toggle[aria-label^="展开 乙公司"]').trigger("click");
    await flushPromises();
    const rows = wrapper.findAll(".ws-children .ws-node");
    const cost = rows.find((item) => item.attributes("aria-label") === "成本发票（监控中）")!;
    await cost.trigger("contextmenu");
    await wrapper.findAll('.ws-sidebar [role="menu"] button').find((item) => item.text() === "选择以进行比较")!.trigger("click");
    expect(wrapper.get(".ws-compare-hint").text()).toContain("成本发票");
    // Payroll has no reconciliation relation with cost invoices; another company's folder is never linked.
    const payroll = rows.find((item) => item.attributes("aria-label") === "工资社保")!;
    await payroll.trigger("contextmenu");
    let compare = wrapper.findAll('.ws-sidebar [role="menu"] button').find((item) => item.text() === "与已选项进行比较")!;
    expect(compare.attributes("disabled")).toBeDefined();
    expect(wrapper.get(".ws-menu__note").text()).toBe("这两类资料之间没有勾稽关系");
    await wrapper.get('.ws-sidebar [role="menu"]').trigger("keydown", { key: "Escape" });
    const otherIssued = wrapper.findAll(".ws-children .ws-node").filter((item) => item.attributes("aria-label") === "开具发票")[1]!;
    await otherIssued.trigger("contextmenu");
    expect(wrapper.get(".ws-menu__note").text()).toBe("不同公司的资料不做关联");
    await wrapper.get('.ws-sidebar [role="menu"]').trigger("keydown", { key: "Escape" });
    // Same company, related pair: the row offers ⇄ directly and opens a compare tab with that relation.
    const issued = wrapper.findAll(".ws-children .ws-row").find((item) => item.find('.ws-node[aria-label="开具发票"]').exists())!;
    await issued.get(".ws-compare").trigger("click");
    await flushPromises();
    expect(tabTitles(wrapper)).toContain("甲公司 · 成本发票 ⇄ 开具发票");
    expect(calls.some((url) => url.includes("/compare?a=cost_invoice_dir&b=issued_invoice_dir"))).toBe(true);
    expect(wrapper.find(".ws-compare-hint").exists()).toBe(false);
  });

  it("refreshes only the active tab on a double click of hi.", async () => {
    stubBackend();
    const { wrapper } = await mountApp();
    await wrapper.get('.ws-toggle[aria-label="展开 甲公司"]').trigger("click");
    await flushPromises();
    await sidebarButton(wrapper, "开具发票").trigger("click");
    await flushPromises();
    const companyLoads = () => calls.filter((url) => url === "/api/v1/companies/co_1/directories").length;
    const invoiceLoads = () => calls.filter((url) => url.includes("/directories/issued_invoice_dir/invoices")).length;
    const [companyBefore, invoicesBefore] = [companyLoads(), invoiceLoads()];
    await wrapper.get(".brand").trigger("dblclick");
    await flushPromises();
    expect(invoiceLoads()).toBe(invoicesBefore + 1); // the active directory tab reloads
    // The directory tab's own header read counts here; the hidden company tab did not reload.
    expect(companyLoads()).toBe(companyBefore + 1);
    expect(tabTitles(wrapper)).toEqual(["甲公司", "甲公司 · 开具发票"]);
  });
});

describe("sidebar width", () => {
  it("stays within 220—460 px and leaves the content at least 620 px", () => {
    expect(clampSidebar(100, 1600, 72)).toEqual({ width: SIDEBAR_MIN, limited: "min" });
    expect(clampSidebar(900, 1600, 72)).toEqual({ width: SIDEBAR_MAX, limited: "max" });
    expect(clampSidebar(400, 1000, 72)).toEqual({ width: 1000 - 72 - CONTENT_MIN, limited: "max" });
    expect(clampSidebar(300.4, 1600, 72)).toEqual({ width: 300, limited: "" });
  });
});
